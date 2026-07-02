"""The analysis funnel — Stages 0-6, run in order, gate-on-fail.

DESIGN RULE (do not violate): Phase 1 (selection: catalyst + valuation) decides
WHAT to trade and which direction. Phase 2 (timing/structure: GEX, OI, volume,
IV) only refines entry/stop/instrument on a thesis that already passed Phase 1.
Positioning data NEVER generates a thesis. A name that fails an early gate exits
(or, for the liquidity gate, drops to share-only) rather than getting scored.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from . import gex as gexmod
from .oi_cache import serve_oi
from .config import (
    BookRules,
    LIQUIDITY,
    SINGLE_NAME_GEX_MIN_MARKET_CAP,
    load_book_rules,
    risk_free_rate,
)
from .greeks import bs_delta, year_fraction
from .models import (
    Catalyst,
    Direction,
    ExpiryChain,
    FunnelResult,
    GexProfile,
    IVReadout,
    OptionChain,
    StageResult,
    TradeStructure,
)
from .providers import Providers

# Tiny per-day cache so we don't pull the heavy SPY chain once per ticker.
_INDEX_GEX_CACHE: dict[tuple[str, date], Optional[GexProfile]] = {}


# --------------------------------------------------------------------------- #
# Option-chain helpers (IV / straddle / delta)                                  #
# --------------------------------------------------------------------------- #
def _mid(row: pd.Series) -> float:
    bid, ask, last = row.get("bid"), row.get("ask"), row.get("lastPrice")
    if pd.notna(bid) and pd.notna(ask) and ask >= bid > 0:
        return float((bid + ask) / 2)
    if pd.notna(last) and last > 0:
        return float(last)
    return float("nan")


def _atm_row(df: pd.DataFrame, spot: float) -> Optional[pd.Series]:
    if df is None or df.empty:
        return None
    idx = (df["strike"] - spot).abs().idxmin()
    return df.loc[idx]


def _atm_iv(ec: ExpiryChain, spot: float) -> Optional[float]:
    rows = [r for r in (_atm_row(ec.calls, spot), _atm_row(ec.puts, spot)) if r is not None]
    ivs = [float(r["impliedVolatility"]) for r in rows
           if pd.notna(r.get("impliedVolatility")) and r["impliedVolatility"] > 0]
    return float(np.mean(ivs)) if ivs else None


def _straddle_price(ec: ExpiryChain, spot: float) -> Optional[float]:
    c, p = _atm_row(ec.calls, spot), _atm_row(ec.puts, spot)
    if c is None or p is None:
        return None
    cm, pm = _mid(c), _mid(p)
    if not (np.isfinite(cm) and np.isfinite(pm)):
        return None
    return cm + pm


def _iv_at_delta(df: pd.DataFrame, spot: float, T: float, right: str, target_delta: float) -> Optional[float]:
    """IV of the strike whose |delta| is nearest target_delta (e.g. 0.25)."""
    if df is None or df.empty:
        return None
    iv = pd.to_numeric(df["impliedVolatility"], errors="coerce").to_numpy(float)
    k = pd.to_numeric(df["strike"], errors="coerce").to_numpy(float)
    ok = np.isfinite(iv) & (iv > 0) & np.isfinite(k)
    if not ok.any():
        return None
    delta = bs_delta(spot, k[ok], T, risk_free_rate(), 0.0, iv[ok], right)
    j = int(np.argmin(np.abs(np.abs(delta) - target_delta)))
    return float(iv[ok][j])


# --------------------------------------------------------------------------- #
# Stage 0 — liquidity gate                                                       #
# --------------------------------------------------------------------------- #
def liquidity_check(chain: OptionChain) -> tuple[bool, dict]:
    ec = chain.nearest(min_dte=1) or (chain.by_expiry[chain.expiries[0]] if chain.expiries else None)
    if ec is None:
        return False, {"reason": "no option expiries available"}
    spot = chain.spot

    def near(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()
        return df.reindex((df["strike"] - spot).abs().sort_values().index).head(LIQUIDITY.near_strike_count)

    nc, npu = near(ec.calls), near(ec.puts)
    near_oi = pd.concat([nc.get("openInterest"), npu.get("openInterest")]).fillna(0)
    max_near_oi = int(near_oi.max()) if len(near_oi) else 0

    atm_call = _atm_row(ec.calls, spot)
    rel_spread = float("inf")
    if atm_call is not None:
        bid, ask = atm_call.get("bid"), atm_call.get("ask")
        if pd.notna(bid) and pd.notna(ask) and (bid + ask) > 0:
            rel_spread = float((ask - bid) / ((ask + bid) / 2))

    total_vol = 0
    for e in chain.expiries:
        c = chain.by_expiry[e]
        total_vol += int(pd.to_numeric(c.calls.get("volume"), errors="coerce").fillna(0).sum())
        total_vol += int(pd.to_numeric(c.puts.get("volume"), errors="coerce").fillna(0).sum())

    detail = {
        "max_near_strike_oi": max_near_oi,
        "atm_rel_spread": round(rel_spread, 4) if np.isfinite(rel_spread) else None,
        "total_contract_volume": total_vol,
        "thresholds": {
            "min_near_strike_oi": LIQUIDITY.min_near_strike_oi,
            "max_rel_spread": LIQUIDITY.max_rel_spread,
            "min_daily_contract_volume": LIQUIDITY.min_daily_contract_volume,
        },
    }
    ok = (
        max_near_oi >= LIQUIDITY.min_near_strike_oi
        and rel_spread <= LIQUIDITY.max_rel_spread
        and total_vol >= LIQUIDITY.min_daily_contract_volume
    )
    return ok, detail


# --------------------------------------------------------------------------- #
# Index GEX backdrop                                                             #
# --------------------------------------------------------------------------- #
def compute_index_gex(providers: Providers, symbol: str = "SPY") -> Optional[GexProfile]:
    key = (symbol, date.today())
    if key in _INDEX_GEX_CACHE:
        return _INDEX_GEX_CACHE[key]
    try:
        chain = providers.options.get_chain(symbol, max_expiries=2)
        prof = gexmod.compute_gex_profile(chain, is_soft=False, note="index backdrop")
    except Exception:
        prof = None
    _INDEX_GEX_CACHE[key] = prof
    return prof


# --------------------------------------------------------------------------- #
# Funnel                                                                         #
# --------------------------------------------------------------------------- #
def analyze(
    symbol: str,
    direction: Optional[Direction],
    providers: Providers,
    book: Optional[BookRules] = None,
    *,
    entry: Optional[float] = None,
    stop: Optional[float] = None,
    target: Optional[float] = None,
    hold_days: int = 10,
    max_expiries: int = 4,
) -> FunnelResult:
    """Run a candidate ticker through the full funnel and return a FunnelResult.

    `max_expiries` trades depth for speed — the interactive Analyze view uses 4
    (richer IV term structure); the morning batch scan uses fewer for throughput.
    """
    book = book or load_book_rules()
    symbol = symbol.upper().strip()
    res = FunnelResult(symbol=symbol, direction=direction)

    # --- Fetch once, reuse across stages. Fail loud on a missing spot. --- #
    res.quote = providers.quotes.get_quote(symbol)
    spot = res.quote.price
    try:
        chain = providers.options.get_chain(symbol, max_expiries=max_expiries)
    except Exception:
        chain = OptionChain(symbol=symbol, spot=spot, as_of=res.quote.as_of,
                            source=providers.options.__class__.__name__, is_delayed=True)
    # Pre-market OI fallback: cache live OI; backfill from cache when zeroed.
    chain, res.oi_as_of = serve_oi(chain, spot)
    try:
        res.fundamentals = providers.fundamentals.get_fundamentals(symbol)
    except Exception:
        res.fundamentals = None

    # ----- Stage 0: liquidity gate (sets share-only; never hard-exits) ----- #
    if chain.expiries:
        ok, detail = liquidity_check(chain)
    else:
        ok, detail = False, {"reason": "no options listed"}
    if ok:
        res.add(StageResult(0, "Liquidity", "pass",
                            "Options liquid enough for a GEX/options layer.", detail))
    else:
        res.share_only = True
        res.add(StageResult(0, "Liquidity", "fail",
                            "Options too thin for GEX — treated as SHARE-ONLY.", detail))

    # ===================== PHASE 1 — SELECTION ============================ #
    # ----- Stage 1: catalyst ----- #
    _stage1_catalyst(res, providers, entry=entry, hold_days=hold_days)

    # ----- Stage 2: valuation / asymmetry (requires a stated bias) ----- #
    if not _stage2_valuation(res, direction):
        res.exited_at = 2
        return res  # hard gate: no direction -> exit rather than score

    # ===================== PHASE 2 — TIMING/STRUCTURE ===================== #
    if res.share_only:
        for n, nm in [(3, "GEX regime"), (4, "OI / volume"), (5, "Implied vol")]:
            res.add(StageResult(n, nm, "skip", "Skipped — share-only (no options layer).", {}))
        _stage6_structure(res, chain, direction, entry, stop, target, hold_days, share_only=True)
        return res

    _stage3_gex(res, chain, providers)
    _stage4_oi_volume(res, chain)
    _stage5_iv(res, chain, hold_days=hold_days, target=target)
    _stage6_structure(res, chain, direction, entry, stop, target, hold_days, share_only=False)
    return res


def _stage1_catalyst(res: FunnelResult, providers: Providers, *, entry, hold_days: int) -> None:
    sym = res.symbol
    try:
        cats = providers.catalysts.get_catalysts(sym)
    except Exception:
        cats = []
    try:
        nxt = providers.catalysts.get_next_earnings(sym)
    except Exception:
        nxt = None
    res.next_earnings = nxt
    res.catalysts = cats

    today = date.today()
    hold_end = today + timedelta(days=hold_days)
    pre_earnings_risk = bool(nxt and today <= nxt <= hold_end)
    if pre_earnings_risk:
        res.catalysts = [Catalyst("earnings", f"Earnings on {nxt.isoformat()}",
                                  source="calendar", when=nxt, dated=True, binary=True)] + cats

    n_dated = sum(1 for c in res.catalysts if c.dated or c.binary)
    summary_bits = [f"{len(cats)} recent news item(s)"]
    if nxt:
        summary_bits.append(f"next earnings {nxt.isoformat()}")
    detail = {"n_news": len(cats), "next_earnings": nxt.isoformat() if nxt else None,
              "pre_earnings_risk": pre_earnings_risk, "n_dated": n_dated}

    if pre_earnings_risk:
        res.warnings.append(
            f"Pre-earnings: a binary print ({nxt.isoformat()}) falls inside the "
            f"~{hold_days}d hold. Default = ~zero-EV; prefer post-earnings continuation."
        )
        res.add(StageResult(1, "Catalyst", "warn",
                            "Catalyst present but a binary earnings print is inside the hold window. "
                            + "; ".join(summary_bits), detail))
    elif cats or nxt:
        res.add(StageResult(1, "Catalyst", "pass", "; ".join(summary_bits), detail))
    else:
        res.add(StageResult(1, "Catalyst", "warn",
                            "No catalyst found — drifting setup, weak Phase-1 basis.", detail))


def _stage2_valuation(res: FunnelResult, direction: Optional[Direction]) -> bool:
    f = res.fundamentals
    score = None
    note_bits = []
    if f and f.ps_ttm is not None and f.revenue_growth_pct is not None:
        if f.revenue_growth_pct > 0:
            score = f.ps_ttm / f.revenue_growth_pct
            note_bits.append(f"value/growth = {score:.3f} (P/S {f.ps_ttm:.1f} ÷ growth {f.revenue_growth_pct:.1f}%)")
        else:
            note_bits.append("revenue growth ≤ 0 — value/growth score N/A")
    else:
        note_bits.append("P/S or revenue growth unavailable — value/growth score N/A")
    res.value_growth_score = score

    if f and (f.analyst_high or f.analyst_low):
        note_bits.append(f"analyst targets {f.analyst_low}–{f.analyst_high}")

    detail = {
        "value_growth_score": score,
        "ps_ttm": f.ps_ttm if f else None,
        "revenue_growth_pct": f.revenue_growth_pct if f else None,
        "analyst_high": f.analyst_high if f else None,
        "analyst_low": f.analyst_low if f else None,
        "market_cap": f.market_cap if f else None,
    }

    if direction not in ("long", "short"):
        res.add(StageResult(2, "Valuation", "fail",
                            "No stated long/short bias — funnel exits (a thesis must precede timing). "
                            + "; ".join(note_bits), detail))
        return False
    res.add(StageResult(2, "Valuation", "pass",
                        f"Bias = {direction}. " + "; ".join(note_bits), detail))
    return True


def _stage3_gex(res: FunnelResult, chain: OptionChain, providers: Providers) -> None:
    market_cap = res.fundamentals.market_cap if res.fundamentals else None
    is_megacap = bool(market_cap and market_cap >= SINGLE_NAME_GEX_MIN_MARKET_CAP)
    note = "" if is_megacap else "Single-name GEX is SOFT (not a liquid mega-cap) — lean on index backdrop."
    prof = gexmod.compute_gex_profile(chain, is_soft=not is_megacap, note=note)
    res.gex = prof
    res.index_gex = compute_index_gex(providers)

    # Optional hosted cross-check (FlashAlpha). Never overrides local values.
    cross = None
    if providers.gex_provider is not None:
        try:
            cross = providers.gex_provider.get_gex(res.symbol, spot=chain.spot)
        except Exception:
            cross = None

    detail = {
        "net_gex": prof.net_gex, "regime": prof.regime, "gamma_flip": prof.gamma_flip,
        "call_wall": prof.call_wall, "put_wall": prof.put_wall, "is_soft": prof.is_soft,
        "index_regime": res.index_gex.regime if res.index_gex else None,
        "cross_check": None,
    }
    if cross is not None:
        detail["cross_check"] = {
            "source": cross.source, "net_gex": cross.net_gex,
            "call_wall": cross.call_wall, "put_wall": cross.put_wall,
            "gamma_flip": cross.gamma_flip,
        }

    regime_word = "range/mean-revert" if prof.regime == "positive" else "trend/amplify"
    msg = f"Net GEX {prof.net_gex:,.0f} → {prof.regime} ({regime_word})."
    if prof.is_soft and res.index_gex:
        msg += f" Index ({res.index_gex.symbol}) backdrop: {res.index_gex.regime}."
    status = "warn" if prof.is_soft else "pass"
    res.add(StageResult(3, "GEX regime", status, msg, detail))


def _stage4_oi_volume(res: FunnelResult, chain: OptionChain) -> None:
    ec = chain.nearest(min_dte=1) or (chain.by_expiry[chain.expiries[0]] if chain.expiries else None)
    if ec is None:
        res.add(StageResult(4, "OI / volume", "skip", "No expiry to inspect.", {}))
        return

    def vol_gt_oi(df: pd.DataFrame, right: str) -> list[dict]:
        if df is None or df.empty:
            return []
        d = df.copy()
        d["volume"] = pd.to_numeric(d["volume"], errors="coerce").fillna(0)
        d["openInterest"] = pd.to_numeric(d["openInterest"], errors="coerce").fillna(0)
        hot = d[(d["volume"] > d["openInterest"]) & (d["volume"] >= 200)]
        hot = hot.sort_values("volume", ascending=False).head(3)
        return [{"strike": float(r.strike), "right": right,
                 "volume": int(r.volume), "oi": int(r.openInterest)}
                for r in hot.itertuples()]

    new_positioning = vol_gt_oi(ec.calls, "C") + vol_gt_oi(ec.puts, "P")
    # OI concentration (feeds gamma; not a standalone magnet).
    oi_top = []
    for df, right in ((ec.calls, "C"), (ec.puts, "P")):
        if df is not None and not df.empty:
            t = df.assign(openInterest=pd.to_numeric(df["openInterest"], errors="coerce").fillna(0)) \
                  .nlargest(2, "openInterest")
            oi_top += [{"strike": float(r.strike), "right": right, "oi": int(r.openInterest)} for r in t.itertuples()]

    detail = {"new_positioning": new_positioning, "oi_concentration": oi_top}
    if new_positioning:
        strikes = ", ".join(f"{x['strike']:g}{x['right']}" for x in new_positioning)
        res.add(StageResult(4, "OI / volume", "pass",
                            f"New positioning (volume ≫ resting OI) at: {strikes}.", detail))
    else:
        res.add(StageResult(4, "OI / volume", "pass",
                            "No strike shows volume materially above resting OI today.", detail))


def _stage5_iv(res: FunnelResult, chain: OptionChain, *, hold_days: int, target: Optional[float]) -> None:
    spot = chain.spot
    exps = chain.expiries
    if not exps:
        res.add(StageResult(5, "Implied vol", "skip", "No expiries.", {}))
        return

    front = chain.nearest(min_dte=1) or chain.by_expiry[exps[0]]
    back = None
    for e in exps:
        if chain.by_expiry[e].dte > front.dte + 20:
            back = chain.by_expiry[e]
            break

    front_iv = _atm_iv(front, spot)
    back_iv = _atm_iv(back, spot) if back else None
    term = (front_iv - back_iv) if (front_iv is not None and back_iv is not None) else None

    T_front = year_fraction(front.dte)
    rr = None
    p25 = _iv_at_delta(front.puts, spot, T_front, "P", 0.25)
    c25 = _iv_at_delta(front.calls, spot, T_front, "C", 0.25)
    if p25 is not None and c25 is not None:
        rr = p25 - c25

    # Expected move to the hold horizon: straddle of the expiry bracketing it.
    horizon = chain.nearest(min_dte=hold_days) or front
    em = _straddle_price(horizon, spot)
    em_pct = (em / spot) if (em and spot) else None

    iv = IVReadout(
        front_atm_iv=front_iv, back_atm_iv=back_iv, iv_term_structure=term,
        risk_reversal_25d=rr, expected_move_dollars=em, expected_move_pct=em_pct,
        front_expiry=front.expiry, back_expiry=back.expiry if back else None,
    )
    res.iv = iv

    bits = []
    if front_iv is not None:
        bits.append(f"front ATM IV {front_iv*100:.0f}%")
    if term is not None:
        bits.append(f"term {term*100:+.0f}pp ({'crush risk' if term > 0 else 'backwardation'})")
    if rr is not None:
        bits.append(f"25Δ RR {rr*100:+.0f}pp ({'downside' if rr > 0 else 'upside'} demand)")
    if em is not None:
        bits.append(f"expected move ±${em:.2f} ({em_pct*100:.1f}%)")

    detail = {
        "front_atm_iv": front_iv, "back_atm_iv": back_iv, "iv_term_structure": term,
        "risk_reversal_25d": rr, "expected_move_dollars": em, "expected_move_pct": em_pct,
        "no_edge": False,
    }
    status = "pass"
    # Expected-move-vs-thesis test: target inside the implied move => no edge.
    if target is not None and em is not None and abs(target - spot) <= em:
        detail["no_edge"] = True
        status = "warn"
        res.warnings.append(
            f"No edge: target ${target:.2f} sits inside the implied move (±${em:.2f}). "
            "The market already prices this move."
        )
        bits.append("⚠ target inside implied move (no edge)")
    if term is not None and term > 0:
        res.warnings.append("Front-month IV richer than back (crush risk) — prefer spreads/shares over naked premium.")

    res.add(StageResult(5, "Implied vol", status, "; ".join(bits) or "IV readout unavailable.", detail))


def _stage6_structure(
    res: FunnelResult,
    chain: OptionChain,
    direction: Optional[Direction],
    entry: Optional[float],
    stop: Optional[float],
    target: Optional[float],
    hold_days: int,
    *,
    share_only: bool,
) -> None:
    spot = chain.spot
    gex = res.gex
    call_wall = gex.call_wall if gex else None
    put_wall = gex.put_wall if gex else None
    flip = gex.gamma_flip if gex else None

    # Instrument from regime (Phase 2): negative gamma -> directional long option;
    # positive gamma (or share-only) -> shares / defined-risk spread.
    if share_only or gex is None or gex.regime == "positive":
        instrument = "shares"
    else:
        instrument = "long_call" if direction == "long" else "long_put"

    # Derive levels from walls when the user hasn't supplied them.
    e = entry if entry is not None else (put_wall if direction == "long" else call_wall) or spot
    if direction == "long":
        t = target if target is not None else (call_wall or round(spot * 1.05, 2))
        s = stop if stop is not None else (
            round((put_wall or e) * 0.98, 2) if (flip is None or flip > e) else round(min(flip, (put_wall or e)) * 0.999, 2)
        )
    else:
        t = target if target is not None else (put_wall or round(spot * 0.95, 2))
        s = stop if stop is not None else round((call_wall or e) * 1.02, 2)

    strike = exp = premium = None
    if instrument in ("long_call", "long_put") and chain.expiries:
        ec = chain.nearest(min_dte=hold_days) or chain.by_expiry[chain.expiries[0]]
        df = ec.calls if instrument == "long_call" else ec.puts
        atm = _atm_row(df, spot)
        if atm is not None:
            strike = float(atm["strike"])
            exp = ec.expiry
            premium = _mid(atm)

    rationale_bits = []
    if gex and not share_only:
        rationale_bits.append(
            f"{gex.regime} gamma → {'directional long option' if instrument != 'shares' else 'shares / defined-risk'}"
        )
        if call_wall:
            rationale_bits.append(f"call wall {call_wall:g} = target, not ceiling")
        if put_wall:
            rationale_bits.append(f"entry near put wall {put_wall:g}; stop below it / gamma flip")
    elif share_only:
        rationale_bits.append("share-only (no options layer); levels are user/manual or spot-relative")

    res.structure = TradeStructure(
        instrument=instrument, direction=direction or "long", entry=float(e),
        stop=float(s), target=float(t), rationale="; ".join(rationale_bits) or "manual levels",
        strike=strike, expiry=exp,
        premium_per_contract=float(premium) if (premium and np.isfinite(premium)) else None,
    )
    detail = {
        "instrument": instrument, "entry": float(e), "stop": float(s), "target": float(t),
        "strike": strike, "premium_per_contract": res.structure.premium_per_contract,
    }
    res.add(StageResult(6, "Structure", "pass",
                        f"{instrument} {direction or ''}: entry {e:.2f} / stop {s:.2f} / target {t:.2f}", detail))

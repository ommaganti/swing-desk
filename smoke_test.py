#!/usr/bin/env python3
"""Zero-key smoke test.

Two parts:
  1. OFFLINE (always runs, deterministic): builds a synthetic liquid chain and a
     synthetic thin chain and asserts local GEX populates and the Stage-0
     liquidity gate correctly drops the thin name to share-only.
  2. ONLINE (best-effort): runs the real funnel on AAPL + SPY with no API keys.
     If the network/yfinance is unavailable, it is reported and skipped, not failed.

Exit code is non-zero only if the deterministic offline checks fail.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone

import pandas as pd

from swingdesk import gex as gexmod
from swingdesk.analysis import analyze, liquidity_check
from swingdesk.models import ExpiryChain, OptionChain


def _chain(symbol: str, spot: float, oi: int, vol: int, spread: float) -> OptionChain:
    strikes = [spot * m for m in (0.9, 0.95, 1.0, 1.05, 1.1)]

    def side(is_call: bool) -> pd.DataFrame:
        mid = 2.0
        return pd.DataFrame({
            "strike": strikes,
            "bid": [mid - spread / 2] * len(strikes),
            "ask": [mid + spread / 2] * len(strikes),
            "lastPrice": [mid] * len(strikes),
            "volume": [vol] * len(strikes),
            "openInterest": [oi] * len(strikes),
            "impliedVolatility": [0.35] * len(strikes),
        })

    ec = ExpiryChain(expiry=date(2026, 12, 18), dte=30, calls=side(True), puts=side(False))
    return OptionChain(symbol=symbol, spot=spot, as_of=datetime.now(tz=timezone.utc),
                       source="synthetic", is_delayed=True, by_expiry={ec.expiry: ec})


def offline_checks() -> bool:
    ok = True

    liquid = _chain("LIQD", 100.0, oi=5000, vol=2000, spread=0.05)
    thin = _chain("THIN", 100.0, oi=50, vol=20, spread=1.50)

    prof = gexmod.compute_gex_profile(liquid)
    print(f"[offline] liquid GEX: net={prof.net_gex:,.0f} regime={prof.regime} "
          f"flip={prof.gamma_flip} walls={prof.put_wall}/{prof.call_wall}")
    if prof.by_strike.empty:
        print("  ! FAIL: local GEX produced no per-strike profile")
        ok = False

    liq_ok, _ = liquidity_check(liquid)
    thin_ok, _ = liquidity_check(thin)
    print(f"[offline] liquidity gate: liquid={liq_ok} thin={thin_ok}")
    if not liq_ok:
        print("  ! FAIL: liquid synthetic chain should PASS the liquidity gate")
        ok = False
    if thin_ok:
        print("  ! FAIL: thin synthetic chain should FAIL the liquidity gate (share-only)")
        ok = False

    return ok


def online_checks() -> None:
    try:
        from swingdesk.providers import build_providers
        providers = build_providers()
    except Exception as e:  # noqa: BLE001
        print(f"[online] skipped — could not build providers: {type(e).__name__}: {e}")
        return
    for sym in ("AAPL", "SPY"):
        try:
            res = analyze(sym, "long", providers, hold_days=10)
            strip = " | ".join(f"{s.stage}:{s.name}={s.status}" for s in res.stages)
            print(f"[online] {sym}: passed={res.passed} share_only={res.share_only}")
            print(f"         {strip}")
            if res.gex:
                print(f"         GEX net={res.gex.net_gex:,.0f} regime={res.gex.regime} "
                      f"walls={res.gex.put_wall}/{res.gex.call_wall} flip={res.gex.gamma_flip}")
        except Exception as e:  # noqa: BLE001
            print(f"[online] {sym}: skipped — {type(e).__name__}: {e}")


def main() -> int:
    print("=== swingdesk smoke test ===")
    offline_ok = offline_checks()
    print("-" * 40)
    online_checks()
    print("-" * 40)
    print("OFFLINE checks:", "PASS" if offline_ok else "FAIL")
    return 0 if offline_ok else 1


if __name__ == "__main__":
    sys.exit(main())

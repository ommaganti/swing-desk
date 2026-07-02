"""Swing-Trade Decision-Support Desk — dark "cockpit" dashboard.

Design system: UI/UX-Pro-Max "Data-Dense Dashboard" (dark), Fira Sans + Fira Code,
navy surfaces with semantic status colors. Read-only. NOT financial advice.

Tabs: Morning (daily snapshot of the watchlist) · Analyze (single-ticker deep
dive) · Positions (open trades re-read daily) · Journal (expectancy). Run:

    streamlit run app.py
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from swingdesk import journal
from swingdesk.analysis import analyze
from swingdesk.config import load_book_rules
from swingdesk.discipline import (
    calendar_check,
    correlation_check,
    expected_move_check,
    premortem_gate,
)
from swingdesk.models import PreMortem
from swingdesk.providers import build_demo_providers, build_providers
from swingdesk.sizing import portfolio_heat_status, size_trade
from swingdesk.snapshot import load_latest, load_watchlist, run_refresh, save_watchlist
from swingdesk.viz import gex_profile_chart, oi_volume_chart

st.set_page_config(page_title="Swing-Trade Desk", page_icon="📊", layout="wide")

BRAND_SVG = (
    '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" style="vertical-align:-4px">'
    '<rect x="3" y="11" width="4" height="9" rx="1" fill="#22C55E"/>'
    '<rect x="10" y="6" width="4" height="14" rx="1" fill="#3B82F6"/>'
    '<rect x="17" y="3" width="4" height="17" rx="1" fill="#F59E0B"/></svg>'
)

# --------------------------------------------------------------------------- #
# Design system — injected CSS                                                  #
# --------------------------------------------------------------------------- #
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600;700&family=Fira+Sans:wght@300;400;500;600;700&display=swap');
:root{
  --bg:#0B0F19; --surface:#151B2B; --surface2:#1C2336; --surface3:#222B40;
  --border:#2A3346; --border2:#3A465E; --text:#F1F5F9; --muted:#94A3B8; --faint:#64748B;
  --blue:#3B82F6; --gold:#F59E0B; --green:#22C55E; --coral:#FB7185; --amber:#F59E0B;
  --red:#EF4444; --slate:#64748B; --mono:'Fira Code',ui-monospace,monospace;
  --sans:'Fira Sans',system-ui,sans-serif;
}
.stApp{ background:var(--bg); }
html,body,[class*="css"],.stApp,p,div,span,label{ font-family:var(--sans); }
[data-testid="stSidebar"]{ background:var(--surface); border-right:1px solid var(--border); }
[data-testid="stHeader"]{ background:transparent; }
h1,h2,h3,h4{ font-family:var(--sans); color:var(--text); letter-spacing:-.01em; }
.block-container{ padding-top:2rem; max-width:1400px; }
.mono{ font-family:var(--mono); font-variant-numeric:tabular-nums; }
.muted{ color:var(--muted); font-size:.82rem; } .faint{ color:var(--faint); font-size:.76rem; }

.brand{ font-size:1.5rem; font-weight:700; color:var(--text); letter-spacing:-.02em; }
.brand .v{ color:var(--faint); font-size:.8rem; font-weight:500; font-family:var(--mono); }

.card{ background:var(--surface); border:1px solid var(--border); border-radius:14px;
       padding:15px 17px; margin-bottom:12px; }
.card.tight{ padding:12px 14px; }
.card h4{ margin:0 0 11px 0; font-size:.72rem; font-weight:600; color:var(--muted);
          text-transform:uppercase; letter-spacing:.07em; }
.spread{ display:flex; justify-content:space-between; align-items:baseline; gap:12px; margin:5px 0; }
.row{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; }

.pill{ display:inline-flex; align-items:center; gap:5px; padding:3px 10px; border-radius:999px;
       font-size:.7rem; font-weight:600; line-height:1.5; border:1px solid transparent; white-space:nowrap; }
.pill-pass,.pill-pos{ background:rgba(34,197,94,.14); color:#4ADE80; border-color:rgba(34,197,94,.35); }
.pill-fail{ background:rgba(239,68,68,.15); color:#F87171; border-color:rgba(239,68,68,.35); }
.pill-warn{ background:rgba(245,158,11,.14); color:#FBBF24; border-color:rgba(245,158,11,.35); }
.pill-skip,.pill-soft{ background:rgba(100,116,139,.16); color:#94A3B8; border-color:rgba(100,116,139,.3); }
.pill-neg{ background:rgba(251,113,133,.14); color:#FB7185; border-color:rgba(251,113,133,.35); }
.pill-tag{ background:var(--surface3); color:#CBD5E1; border-color:var(--border2); }
.pill-info{ background:rgba(59,130,246,.14); color:#60A5FA; border-color:rgba(59,130,246,.35); }

.dot{ width:9px; height:9px; border-radius:50%; display:inline-block; margin-right:4px; }
.dot-pass,.dot-pos{ background:var(--green); } .dot-fail{ background:var(--red); }
.dot-warn{ background:var(--amber); } .dot-skip{ background:var(--slate); }

.kpi{ display:flex; flex-direction:column; gap:1px; }
.kpi .label{ font-size:.64rem; text-transform:uppercase; letter-spacing:.07em; color:var(--faint); }
.kpi .val{ font-family:var(--mono); font-size:1.3rem; font-weight:600; color:var(--text); font-variant-numeric:tabular-nums; }
.kpi .sub{ font-size:.7rem; color:var(--muted); font-family:var(--mono); }
.big{ font-family:var(--mono); font-size:1.55rem; font-weight:700; color:var(--text); }

.chip{ display:inline-flex; align-items:center; gap:6px; padding:5px 11px; border-radius:8px;
       font-size:.74rem; font-weight:500; background:var(--surface2); border:1px solid var(--border);
       color:var(--muted); font-family:var(--mono); }
.chip.fresh{ color:#4ADE80; border-color:rgba(34,197,94,.3); }
.chip.stale{ color:#FBBF24; border-color:rgba(245,158,11,.3); }
.chip .k{ color:var(--faint); }

.levels{ display:flex; gap:6px; margin:6px 0; }
.lvl{ flex:1; text-align:center; padding:7px 4px; border-radius:9px; background:var(--surface2); border:1px solid var(--border); }
.lvl .l{ font-size:.6rem; text-transform:uppercase; color:var(--faint); letter-spacing:.05em; }
.lvl .v{ font-family:var(--mono); font-weight:600; font-size:.98rem; }
.lvl.stop .v{ color:#F87171; } .lvl.entry .v{ color:#E2E8F0; } .lvl.target .v{ color:#4ADE80; }

.check{ padding:9px 12px; border-radius:10px; background:var(--surface2); border:1px solid var(--border);
        border-left-width:3px; margin-bottom:7px; font-size:.85rem; color:var(--text); }
.check b{ color:var(--text); } .check-block{ border-left-color:var(--red); }
.check-warn{ border-left-color:var(--amber); } .check-ok{ border-left-color:var(--green); }
.check-info{ border-left-color:var(--blue); }

.banner{ padding:11px 15px; border-radius:11px; font-size:.82rem; margin-bottom:10px;
         background:rgba(245,158,11,.08); border:1px solid rgba(245,158,11,.25); color:#FCD34D; }
.banner.demo{ background:rgba(59,130,246,.08); border-color:rgba(59,130,246,.3); color:#93C5FD; }
button[data-baseweb="tab"]{ font-weight:600; }
[data-testid="stMetricValue"]{ font-family:var(--mono); }
@media (prefers-reduced-motion: reduce){ *{ transition:none!important; animation:none!important; } }
</style>
""",
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #
def pill(text: str, kind: str) -> str:
    return f'<span class="pill pill-{kind}">{text}</span>'


def funnel_dots(res) -> str:
    cls = {"pass": "pass", "fail": "fail", "warn": "warn", "skip": "skip"}
    return "".join(f'<span class="dot dot-{cls.get(s.status,"skip")}"></span>' for s in res.stages)


def kpi(label: str, val: str, sub: str | None = None, color: str | None = None) -> str:
    cstyle = f"color:{color};" if color else ""
    subhtml = f'<div class="sub">{sub}</div>' if sub else ""
    return f'<div class="kpi"><div class="label">{label}</div><div class="val" style="{cstyle}">{val}</div>{subhtml}</div>'


def card(html: str) -> None:
    st.markdown(f'<div class="card">{html}</div>', unsafe_allow_html=True)


@st.cache_resource(show_spinner=False)
def get_providers(demo: bool = False):
    return build_demo_providers() if demo else build_providers()


book = load_book_rules()


# --------------------------------------------------------------------------- #
# Sidebar — global controls + candidate form                                    #
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.markdown(f'<div class="brand">{BRAND_SVG} Swing-Trade Desk <span class="v">v0.2</span></div>',
                unsafe_allow_html=True)
    st.caption(f"${book.book_size:,.0f} book · {book.default_risk_pct*100:.0f}% risk/trade · read-only")
    demo_mode = st.toggle("Demo data (synthetic)", value=False,
                          help="Free feeds sometimes return zeroed open interest outside market hours, "
                               "which empties the GEX layer. Demo loads a realistic synthetic liquid chain.")
    providers = get_providers(demo_mode)

    st.divider()
    st.markdown("**Watchlist**")
    wl_text = st.text_area("tickers (comma/space separated)", value=", ".join(load_watchlist()),
                           label_visibility="collapsed", height=70)
    if st.button("Save watchlist", use_container_width=True):
        toks = [t.strip().upper() for t in wl_text.replace("\n", " ").replace(",", " ").split() if t.strip()]
        save_watchlist(toks)
        st.toast(f"Saved {len(toks)} tickers")

    st.divider()
    st.markdown("**Analyze a candidate**")
    symbol = st.text_input("Ticker", value="AAPL").strip().upper()
    direction = st.radio("Bias", ["long", "short"], horizontal=True)
    hold_days = st.number_input("Hold horizon (days)", 1, 120, 10)
    risk_pct = st.slider("Risk per trade (%)", 1.0, 20.0, book.default_risk_pct * 100, 0.5) / 100.0
    binary_event = st.checkbox("Held across a binary print (halve risk)")
    with st.expander("Levels (optional — else from walls)"):
        entry_in = st.number_input("Entry", value=0.0, step=0.01, format="%.2f")
        stop_in = st.number_input("Stop", value=0.0, step=0.01, format="%.2f")
        target_in = st.number_input("Target", value=0.0, step=0.01, format="%.2f")
    run = st.button("Analyze ↗", type="primary", use_container_width=True)
    st.caption(f"Options: **{providers.options_source}** · Catalysts: **{providers.catalyst_source}** · "
               f"GEX cross-check: **{providers.gex_cross_check_source or 'local only'}**")


def _opt(x: float):
    return x if x and x > 0 else None


if run and symbol:
    with st.spinner(f"Running the funnel on {symbol}…"):
        try:
            res = analyze(symbol, direction, providers, book, entry=_opt(entry_in),
                          stop=_opt(stop_in), target=_opt(target_in), hold_days=int(hold_days))
            st.session_state["funnel"] = res
            st.session_state["params"] = {"risk_pct": risk_pct, "binary_event": binary_event,
                                          "hold_days": int(hold_days)}
        except Exception as e:  # noqa: BLE001
            st.session_state.pop("funnel", None)
            st.error(f"Analysis failed for {symbol}: {type(e).__name__}: {e}")


# --------------------------------------------------------------------------- #
# Header + freshness                                                             #
# --------------------------------------------------------------------------- #
if "snapshot" not in st.session_state:
    st.session_state["snapshot"] = load_latest()
snap = st.session_state["snapshot"]

hl, hr = st.columns([3, 1])
with hl:
    st.markdown(f'<div class="brand" style="font-size:1.7rem">{BRAND_SVG} Swing-Trade Decision-Support Desk</div>',
                unsafe_allow_html=True)
with hr:
    if st.button("↻ Refresh now", use_container_width=True):
        with st.spinner("Pulling fresh data for the watchlist + positions…"):
            st.session_state["snapshot"] = run_refresh(demo=demo_mode)
        st.rerun()

# freshness + source chips
chips = []
if snap is not None:
    fresh_cls = "fresh" if snap.age_hours < 18 else "stale"
    demo_tag = ' · <span style="color:#93C5FD">demo</span>' if snap.demo else ""
    chips.append(f'<span class="chip {fresh_cls}"><span class="k">as of</span> {snap.as_of}{demo_tag}</span>')
    chips.append(f'<span class="chip"><span class="k">watchlist</span> {len(snap.results)}/{len(snap.watchlist)}</span>')
    chips.append(f'<span class="chip"><span class="k">positions</span> {len(snap.positions)}</span>')
else:
    chips.append('<span class="chip stale"><span class="k">no snapshot</span> — click Refresh now</span>')
chips.append(f'<span class="chip"><span class="k">book</span> ${book.book_size:,.0f} · {book.default_risk_pct*100:.0f}%/trade</span>')
st.markdown('<div class="row" style="margin:6px 0 14px">' + " ".join(chips) + "</div>", unsafe_allow_html=True)

st.markdown(
    '<div class="banner"><b>Not financial advice.</b> Decision-support only — scenarios with stops and '
    'sizing, never recommendations or price predictions. No broker execution. Option/GEX data via yfinance '
    'is delayed (~15 min); greeks are model-derived.</div>', unsafe_allow_html=True)
if demo_mode:
    st.markdown('<div class="banner demo"><b>Demo data</b> — synthetic liquid chain. Figures are illustrative, '
                'not market data. Turn off in the sidebar for live providers.</div>', unsafe_allow_html=True)

tab_morning, tab_analyze, tab_positions, tab_journal = st.tabs(
    ["🌅 Morning", "🔬 Analyze", "📈 Positions", "📒 Journal"])


# --------------------------------------------------------------------------- #
# Morning — watchlist snapshot grid                                             #
# --------------------------------------------------------------------------- #
def morning_card_html(tkr: str, res) -> str:
    if res is None:
        return f'<div class="card tight"><div class="spread"><span class="mono" style="font-size:1.1rem;font-weight:700">{tkr}</span>{pill("error","fail")}</div><div class="faint">analysis failed this run</div></div>'
    g = res.gex
    spot = res.quote.price if res.quote else None
    spot_s = f"${spot:,.2f}" if spot else "—"
    regime = pill(g.regime.upper(), "pos" if g.regime == "positive" else "neg") if g else pill("no gex", "skip")
    soft = pill("soft", "soft") if (g and g.is_soft) else ""
    share = pill("share-only", "warn") if res.share_only else ""
    oi_cached = pill("OI cached", "tag") if (res.oi_as_of and res.oi_as_of != "live") else ""
    netgex = f"{g.net_gex:,.0f}" if g else "—"
    walls = (f"{g.put_wall:g} / {g.call_wall:g}" if (g and g.put_wall and g.call_wall) else "—")
    earn = res.next_earnings.isoformat() if res.next_earnings else "—"
    return (
        f'<div class="card tight">'
        f'<div class="spread"><div><span class="mono" style="font-size:1.15rem;font-weight:700">{tkr}</span> '
        f'<span class="faint mono">{spot_s}</span></div><div class="row">{regime} {soft} {share} {oi_cached}</div></div>'
        f'<div style="margin:9px 0 11px">{funnel_dots(res)}</div>'
        f'<div class="spread"><span class="faint">net GEX</span><span class="mono">{netgex}</span></div>'
        f'<div class="spread"><span class="faint">put / call wall</span><span class="mono">{walls}</span></div>'
        f'<div class="spread"><span class="faint">catalysts · earnings</span><span class="mono">{len(res.catalysts)} · {earn}</span></div>'
        f"</div>"
    )


with tab_morning:
    if snap is None:
        st.info("No snapshot yet. Click **↻ Refresh now** (top right) to pull the watchlist. "
                "It also runs automatically each weekday morning via the launchd agent.")
    else:
        st.caption("Daily snapshot · neutral default bias · click a ticker to load it into Analyze")
        tickers = snap.watchlist
        ncol = 3
        for i in range(0, len(tickers), ncol):
            cols = st.columns(ncol)
            for j, tkr in enumerate(tickers[i:i + ncol]):
                with cols[j]:
                    res = snap.results.get(tkr)
                    st.markdown(morning_card_html(tkr, res), unsafe_allow_html=True)
                    if res is not None and st.button(f"Analyze {tkr}", key=f"m_{tkr}", use_container_width=True):
                        st.session_state["funnel"] = res
                        st.session_state["params"] = {"risk_pct": book.default_risk_pct,
                                                      "binary_event": False, "hold_days": 10}
                        st.toast(f"Loaded {tkr} → open the Analyze tab")
        if snap.errors:
            st.caption("Errors this run: " + ", ".join(f"{k} ({v})" for k, v in snap.errors.items()))


# --------------------------------------------------------------------------- #
# Analyze — single-ticker deep dive                                             #
# --------------------------------------------------------------------------- #
def render_analyze(res, providers, params):
    spot = res.quote.price if res.quote else None
    head = f'{res.symbol} · {res.direction}' + (f' · spot ${spot:,.2f}' if spot else '')
    st.markdown(f'<div class="brand" style="font-size:1.5rem">{head}</div>', unsafe_allow_html=True)
    if res.share_only:
        st.markdown(pill("SHARE-ONLY · options too thin for a GEX layer", "warn"), unsafe_allow_html=True)

    strip = " ".join(pill(f"{s.stage}·{s.name}: {s.status.upper()}",
                          {"pass": "pass", "fail": "fail", "warn": "warn", "skip": "skip"}[s.status])
                     for s in res.stages)
    st.markdown(f'<div class="card tight"><h4>Funnel</h4><div class="row">{strip}</div></div>', unsafe_allow_html=True)
    if not res.passed:
        st.error(f"Funnel exited at Stage {res.exited_at}. Fix the failing gate "
                 "(a thesis must precede timing) and re-run.")

    c1, c2 = st.columns(2)
    with c1:
        g = res.gex
        if g is not None:
            rp = pill(g.regime.upper(), "pos" if g.regime == "positive" else "neg")
            soft = pill("soft", "soft") if g.is_soft else ""
            idx = (f'<div class="muted">index backdrop ({res.index_gex.symbol}): {res.index_gex.regime}</div>'
                   if res.index_gex else "")
            cross = ""
            for s in res.stages:
                if s.stage == 3 and s.detail.get("cross_check"):
                    cc = s.detail["cross_check"]
                    cross = (f'<div class="muted">cross-check ({cc["source"]}): walls '
                             f'{cc.get("put_wall")}/{cc.get("call_wall")}, flip {cc.get("gamma_flip")}</div>')
            flip = f"{g.gamma_flip:g}" if g.gamma_flip is not None else "—"
            cw = f"{g.call_wall:g}" if g.call_wall is not None else "—"
            pw = f"{g.put_wall:g}" if g.put_wall is not None else "—"
            oi_note = ""
            if res.oi_as_of and res.oi_as_of != "live":
                oi_note = (f'<div class="muted">OI as of <b>{res.oi_as_of}</b> '
                           f'(cached — pre-market fallback; OI is a daily figure)</div>')
            card(f'<h4>GEX regime · Phase 2 &nbsp; {rp} {soft}</h4>'
                 f'<div class="big">net GEX {g.net_gex:,.0f}</div>'
                 f'<div class="spread"><span class="faint">gamma flip</span><span class="mono">{flip}</span></div>'
                 f'<div class="spread"><span class="faint">put wall · call wall</span><span class="mono">{pw} · {cw}</span></div>'
                 + idx + cross + oi_note)
        else:
            card('<h4>GEX regime · Phase 2</h4><div class="muted">No options layer (share-only or no data).</div>')

        f = res.fundamentals
        vs = f"{res.value_growth_score:.3f}" if res.value_growth_score is not None else "—"
        details = ""
        if f:
            details = (f'<div class="muted">P/S {f.ps_ttm} · rev growth {f.revenue_growth_pct}% · '
                       f'targets {f.analyst_low}–{f.analyst_high} · {f.sector or "—"}</div>')
        card(f'<h4>Valuation / asymmetry · Phase 1</h4><div class="big">value/growth {vs}</div>'
             f'<div class="faint">lower = more growth per valuation $</div>{details}'.replace("None", "—"))

    with c2:
        rows = ""
        for cat in res.catalysts[:7]:
            tag = pill("dated·binary" if cat.binary else ("dated" if cat.dated else "undated"),
                       "warn" if cat.binary else "tag")
            when = cat.when.isoformat() if cat.when else ""
            rows += f'<div style="margin:5px 0">{tag} <b>{cat.kind}</b> <span class="faint">{when}</span><br><span class="muted">{cat.headline[:96]}</span></div>'
        if not rows:
            rows = '<div class="muted">No catalysts found.</div>'
        ne = f'<div class="faint" style="margin-top:6px">next earnings: {res.next_earnings.isoformat()}</div>' if res.next_earnings else ""
        card(f'<h4>Catalysts · Phase 1</h4>{rows}{ne}')

        iv = res.iv
        if iv:
            def pc(x): return f"{x*100:.0f}%" if x is not None else "—"
            def pp(x): return f"{x*100:+.0f}pp" if x is not None else "—"
            em = f"±${iv.expected_move_dollars:.2f} ({pc(iv.expected_move_pct)})" if iv.expected_move_dollars else "—"
            card(f'<h4>Implied vol · Phase 2</h4>'
                 f'<div class="spread"><span class="faint">front ATM IV · term</span>'
                 f'<span class="mono">{pc(iv.front_atm_iv)} · {pp(iv.iv_term_structure)} '
                 f'{"(crush)" if (iv.iv_term_structure or 0) > 0 else ""}</span></div>'
                 f'<div class="spread"><span class="faint">25Δ risk reversal</span><span class="mono">{pp(iv.risk_reversal_25d)}</span></div>'
                 f'<div class="spread"><span class="faint">expected move</span><span class="mono">{em}</span></div>')

    for w in res.warnings:
        st.markdown(f'<div class="check check-warn">{w}</div>', unsafe_allow_html=True)

    if res.gex is not None and not res.gex.by_strike.empty:
        gc1, gc2 = st.columns(2)
        gc1.plotly_chart(gex_profile_chart(res.gex), use_container_width=True)
        try:
            chain = providers.options.get_chain(res.symbol, max_expiries=2)
            ec = chain.nearest(min_dte=1) or chain.by_expiry[chain.expiries[0]]
            gc2.plotly_chart(oi_volume_chart(ec, chain.spot), use_container_width=True)
        except Exception:
            gc2.info("OI/volume view unavailable.")

    st.markdown("#### Pre-mortem <span class='faint'>(required before sizing)</span>", unsafe_allow_html=True)
    pc_ = st.columns(3)
    bear = pc_[0].text_area("Bear case", key="pm_bear", height=104, placeholder="What breaks this thesis?")
    inval = pc_[1].text_area("Invalidation evidence", key="pm_invalid", height=104,
                             placeholder="The specific signal that says you're wrong.")
    base = pc_[2].text_area("Historical base rate", key="pm_base", height=104,
                            placeholder="How often has this setup worked before?")
    pm = PreMortem(bear, inval, base)

    st.markdown("#### Discipline")
    gate = premortem_gate(pm)
    open_sectors = journal.open_position_sectors(
        lambda t: providers.fundamentals.get_fundamentals(t).sector)
    sector = res.fundamentals.sector if res.fundamentals else None
    checks = [gate, expected_move_check(res),
              correlation_check(sector, open_sectors, res.symbol),
              calendar_check(params.get("hold_days", 10))]
    for chk in checks:
        st.markdown(f'<div class="check check-{chk.level}"><b>{chk.name}:</b> {chk.message}</div>',
                    unsafe_allow_html=True)

    st.markdown("#### Sizing")
    if gate.blocks_sizing:
        st.markdown('<div class="check check-block"><b>Locked.</b> Complete the pre-mortem above to unlock sizing.</div>',
                    unsafe_allow_html=True)
    elif res.structure is None:
        st.info("No structure to size.")
    else:
        s = res.structure
        sr = size_trade(s, book, risk_pct=params.get("risk_pct"), binary_event=params.get("binary_event", False))
        heat = portfolio_heat_status(journal.open_risk_dollars(), sr.risk_dollars, book)
        qlabel = "Contracts" if s.instrument != "shares" else "Shares"
        max_loss_pct = sr.max_loss_dollars / book.book_size * 100
        kpis = "".join([
            f'<div style="flex:1">{kpi("Instrument", s.instrument)}</div>',
            f'<div style="flex:1">{kpi("Risk budget", f"${sr.risk_dollars:.0f}", f"{sr.risk_pct*100:.1f}% of book")}</div>',
            f'<div style="flex:1">{kpi(qlabel, str(sr.quantity))}</div>',
            f'<div style="flex:1">{kpi("Max loss", f"${sr.max_loss_dollars:.0f}", f"{max_loss_pct:.1f}% of book", color="#F87171" if max_loss_pct>book.per_position_cap_pct*100 else None)}</div>',
            f'<div style="flex:1">{kpi("Position", f"${sr.position_dollars:,.0f}", f"{sr.position_pct_of_book*100:.1f}% of book")}</div>',
        ])
        levels = (f'<div class="levels"><div class="lvl entry"><div class="l">entry</div><div class="v">{s.entry:.2f}</div></div>'
                  f'<div class="lvl stop"><div class="l">stop</div><div class="v">{s.stop:.2f}</div></div>'
                  f'<div class="lvl target"><div class="l">target</div><div class="v">{s.target:.2f}</div></div></div>')
        card(f'<div class="row" style="gap:18px;align-items:flex-start">{kpis}</div>{levels}'
             f'<div class="faint" style="margin-top:6px">{s.rationale}</div>')
        if not sr.feasible:
            st.markdown('<div class="check check-warn"><b>Not sizable</b> within the rules as structured — see notes.</div>',
                        unsafe_allow_html=True)
        for n in sr.notes:
            st.markdown(f'<div class="check check-warn">{n}</div>', unsafe_allow_html=True)
        heat_cls = "check-ok" if heat.within_cap else "check-block"
        st.markdown(f'<div class="check {heat_cls}"><b>Portfolio heat:</b> {heat.message}</div>', unsafe_allow_html=True)

        with st.expander("Log this trade to the journal"):
            setup = st.text_input("Setup / catalyst bucket",
                                  value=(res.catalysts[0].kind if res.catalysts else "discretionary"))
            if st.button("Log trade"):
                tid = journal.log_trade({
                    "ticker": res.symbol, "setup_type": setup, "direction": res.direction,
                    "instrument": s.instrument, "regime_tag": res.gex.regime if res.gex else "share-only",
                    "entry": s.entry, "stop": s.stop, "target": s.target, "size": sr.quantity,
                    "risk_dollars": sr.risk_dollars,
                    "implied_move": res.iv.expected_move_dollars if res.iv else None,
                    "realized_move": None, "outcome": "open", "pnl": None,
                    "premortem_bear": pm.bear_case, "premortem_invalidation": pm.invalidation_evidence,
                    "premortem_base_rate": pm.historical_base_rate,
                })
                st.success(f"Logged trade #{tid} (status: open).")


with tab_analyze:
    res = st.session_state.get("funnel")
    if res is None:
        st.info("Use the sidebar **Analyze a candidate** form, or click a ticker on the **Morning** tab.")
    else:
        render_analyze(res, providers, st.session_state.get("params", {}))


# --------------------------------------------------------------------------- #
# Positions — open trades re-read daily                                         #
# --------------------------------------------------------------------------- #
with tab_positions:
    positions = snap.positions if snap else []
    if not positions:
        st.info("No open positions. Log a trade from the **Analyze** tab; open trades are re-read "
                "each morning (current price, unrealized move, and a fresh GEX regime read).")
    else:
        st.caption("Open trades, re-read in the latest snapshot. Regime can flip after OPEX — watch the flags.")
        for p in positions:
            cur = f"${p.current_price:,.2f}" if p.current_price else "—"
            unreal = (f'{p.unrealized_move:+.2f}' if p.unrealized_move is not None else "—")
            ucolor = "#4ADE80" if (p.unrealized_move or 0) >= 0 else "#F87171"
            udol = (f' · ${p.unrealized_dollars:+,.0f}' if p.unrealized_dollars is not None else "")
            flip = pill("REGIME FLIPPED", "warn") if p.regime_flipped else (
                pill(p.current_regime or "—", "pos" if p.current_regime == "positive" else "neg") if p.current_regime else "")
            tgt = f'{p.dist_to_target_pct:+.1f}%' if p.dist_to_target_pct is not None else "—"
            stp = f'{p.dist_to_stop_pct:+.1f}%' if p.dist_to_stop_pct is not None else "—"
            kpis = "".join([
                f'<div style="flex:1">{kpi("Current", cur)}</div>',
                f'<div style="flex:1">{kpi("Unrealized", unreal + udol, color=ucolor)}</div>',
                f'<div style="flex:1">{kpi("to target", tgt)}</div>',
                f'<div style="flex:1">{kpi("to stop", stp)}</div>',
            ])
            card(f'<div class="spread"><div><span class="mono" style="font-size:1.1rem;font-weight:700">{p.ticker}</span> '
                 f'<span class="faint">{p.direction} · {p.instrument} · {p.size:g} · entry {p.entry:.2f}</span></div>'
                 f'<div class="row">{flip}</div></div>'
                 f'<div class="row" style="gap:18px;margin-top:8px">{kpis}</div>'
                 + (f'<div class="faint" style="margin-top:6px">{p.note}</div>' if p.note else ""))


# --------------------------------------------------------------------------- #
# Journal — expectancy + trades                                                 #
# --------------------------------------------------------------------------- #
with tab_journal:
    st.markdown("#### Expectancy by setup bucket")
    exp = journal.expectancy_by_bucket()
    if exp.empty:
        st.info("No closed trades yet. Log trades from Analyze, then set outcomes below.")
    else:
        show = exp.copy()
        show["expectancy"] = show.apply(
            lambda r: f"${r['expectancy']:.2f}" + ("" if r["significant"] else f"  (n={int(r['n'])} · not yet significant)"),
            axis=1)
        st.dataframe(show[["setup_type", "n", "wins", "losses", "win_rate", "avg_win", "avg_loss", "expectancy"]],
                     use_container_width=True, hide_index=True)
        st.caption("Expectancy = win_rate·avg_win − loss_rate·avg_loss. Under ~30 trades, treat as directional only.")

    st.markdown("#### Trades")
    trades = journal.list_trades()
    if trades.empty:
        st.info("No trades logged.")
    else:
        st.dataframe(trades, use_container_width=True, hide_index=True)
        with st.expander("Close / update an open trade"):
            open_ids = trades[trades["outcome"].fillna("open") == "open"]["id"].tolist()
            if not open_ids:
                st.caption("No open trades.")
            else:
                tid = st.selectbox("Trade id", open_ids)
                oc = st.selectbox("Outcome", ["win", "loss", "scratch"])
                pnl = st.number_input("Realized P/L ($)", value=0.0, step=1.0, format="%.2f")
                realized = st.number_input("Realized move ($, optional)", value=0.0, step=0.01, format="%.2f")
                if st.button("Update trade"):
                    con = journal.init_db()
                    con.execute("UPDATE trades SET outcome=?, pnl=?, realized_move=? WHERE id=?",
                                (oc, pnl, realized or None, int(tid)))
                    con.commit()
                    con.close()
                    st.success(f"Updated trade #{tid}. Re-open the tab to refresh expectancy.")

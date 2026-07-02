# Swing-Trade Decision-Support Desk

A **local, read-only** decision-support tool for swing trading a small (**$2,000**) account. It pulls market data each morning, runs each candidate ticker through a strict two-phase funnel, and presents the result as a dark, card-based Streamlit **cockpit** (Morning · Analyze · Positions · Journal) with a sizing-ready trade plan.

**Daily by default:** a `refresh.py` job (auto-run each weekday morning via launchd) snapshots the whole watchlist and re-reads every open position; the dashboard loads that snapshot and stamps an honest *"as of"* time. **Risk profile:** 10% of equity per trade ($200), with scaled caps — see *Risk profile* below.

> **Not financial advice.** This is decision-support. It surfaces structured data, risk-based sizing math, and discipline gates. Outputs are *scenarios with stops and sizing*, never recommendations and never short-term price predictions. It **never** places trades, connects to a broker for execution, or writes to any account.

## The core principle (two jobs, never blended)

- **Phase 1 — selection** decides *what* to trade and *which direction*: **catalyst + valuation**.
- **Phase 2 — timing/structure** decides *when* to enter and *how* to structure it: **GEX, open interest, volume, implied vol**.

Positioning data (GEX/OI) **never generates a thesis** — it only refines entry, stop, and instrument on a thesis that already passed Phase 1. The funnel **short-circuits**: a ticker that fails an early gate exits (or drops to share-only) rather than getting a worse score.

## Runs with zero API keys

Out of the box (no keys, no cost):
- **Quotes / fundamentals / earnings / option chains** → `yfinance`
- **GEX** (net GEX, gamma flip, call/put walls) → **computed locally** from the chain via Black-Scholes gamma
- **Catalysts** → `yfinance` news headlines
- **OPEX / macro** → local 3rd-Friday math + a maintained `data/fomc_cpi_dates.json`

Option/GEX data via yfinance is **delayed (~15 min)** and greeks are **model-derived** — the UI flags this.

## Optional API keys (all free tiers; add only what you want)

Copy `.env.example` to `.env` and fill in any subset. Keys are loaded with `python-dotenv` and are **never printed, logged, or committed** (`.env` is git-ignored).

| Key | What it adds | Free tier | Where |
|---|---|---|---|
| `TRADIER_API_KEY` | **Real option-chain OI + native greeks** (delta/gamma/theta/vega + IV via ORATS). Fixes yfinance's zeroed off-hours OI so GEX is built on real OI × real gamma. **Wired** — used for chains whenever the key is set. | free with an account (sandbox = delayed) | https://tradier.com |
| `FINNHUB_API_KEY` | Better **catalysts** only: structured news + earnings calendar. *(Finnhub free does **not** include options OI — that's what Tradier is for.)* | 60 calls/min (~300/day) | https://finnhub.io |
| `FLASHALPHA_API_KEY` | Hosted GEX **cross-check** of local walls/flip | 5 GEX requests/day | https://flashalpha.com |

Without any keys the tool runs zero-key (yfinance + local GEX + yfinance-news catalysts). `POLYGON_API_KEY` / `TIINGO_API_KEY` are reserved for future adapters. Alpha Vantage was intentionally **not** used — its free tier is now 25 requests/day.

> **Real OI / pre-market OI:** yfinance returns **zeroed open interest outside market hours**, which would empty the GEX layer. Open interest is a *once-daily* figure (OCC settles it overnight), so the tool ships a **free pre-market cache** (`swingdesk/oi_cache.py`): the midday auto-run captures the live chain, and the pre-market run reuses it — populating GEX with OI labelled *"OI as of \<time\>"* (≈1 session stale at most, which is fine for multi-day swing setups). For the *freshly-settled* figure at any hour, set `TRADIER_API_KEY` (real OI + greeks) — it overrides the cache automatically. The sidebar **Demo data** toggle shows the full experience offline.

> **FlashAlpha note:** the exact endpoint/field names can change. If the hosted cross-check numbers don't appear, set `FLASHALPHA_BASE_URL` / `FLASHALPHA_GEX_PATH` in `.env` to match the current [docs](https://flashalpha.com/docs/lab-api-gex). The adapter fails safe to local GEX, which is always the source of truth.

## Install & run

Requires **Python 3.11+** (this machine's `python3` is 3.9 — use `python3.11`).

```bash
git clone <your-fork-url> swing-desk && cd swing-desk   # or just: cd swing-desk
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock   # exact tested versions (reproducible)
# or: pip install -r requirements.txt   (looser floors)
# or: pip install -e ".[dev]"          (installs the package + the swingdesk-refresh command)

# (optional) add keys
cp .env.example .env   # then edit

# pull a first snapshot (use --demo for synthetic data with no network)
python refresh.py            # or: python refresh.py --demo

# run the dashboard
streamlit run app.py
```

The cockpit opens on **Morning** (the daily watchlist snapshot). Click a ticker (or use the sidebar **Analyze a candidate** form) to open the **Analyze** deep-dive; **Positions** shows open trades re-read daily; **Journal** holds the expectancy table. The sidebar **Demo data** toggle loads a synthetic liquid chain when live feeds return zeroed open interest (common outside market hours).

### Daily auto-refresh (launchd)

Install the morning job so the watchlist + open positions refresh automatically each weekday (default 8:00 local):

```bash
scripts/install_launchd.sh          # 8am; pass an hour, e.g. scripts/install_launchd.sh 7
launchctl start com.swingdesk.refresh   # run it once now
scripts/uninstall_launchd.sh        # remove later
```

It writes a dated snapshot to `data/snapshots/` and logs to `data/refresh.log`. Edit the watchlist in `data/watchlist.json` or from the sidebar.

### Sanity checks

```bash
python smoke_test.py     # zero-key end-to-end + deterministic offline checks
pytest -q                # unit tests (greeks, GEX, sizing, discipline, calendar, journal, funnel)
```

### Run in Docker (reproducible, cross-platform)

```bash
docker build -t swingdesk .
docker run --rm -p 8501:8501 \
    --env-file .env \
    -v "$(pwd)/data:/app/data" \
    swingdesk
# open http://localhost:8501
```

The `-v .../data` volume persists the journal, snapshots, and OI cache. Secrets are passed via `--env-file` (never baked into the image). The macOS launchd auto-refresh doesn't apply in a container — schedule `swingdesk-refresh` with cron or your platform's scheduler instead.

> **Distribution notes:** licensed **MIT** (`LICENSE` — set your own copyright holder). Versions are pinned in `requirements.lock` and declared in `pyproject.toml`. This is a **local, single-user, read-only** tool and **not financial advice**; anyone running it does so at their own risk. It is *not* hardened for public multi-user hosting (no auth; yfinance is often rate-limited from datacenter IPs — use a keyed provider there).

## The funnel (Stages 0–6)

| Stage | Phase | What it does | Gate behavior |
|---|---|---|---|
| 0 Liquidity | pre | Thousands of OI at near strikes, tight bid/ask, real volume | Fail → **share-only** (no options/GEX layer) |
| 1 Catalyst | 1 | News + next earnings + regulatory; tags dated/binary vs undated | Pre-earnings entries flagged ~zero-EV |
| 2 Valuation | 1 | `value/growth = P/S ÷ revenue-growth%`; analyst targets | **Requires a stated long/short bias → else exits** |
| 3 GEX regime | 2 | net GEX sign, gamma flip, call/put walls; single-name only for mega-caps (else index backdrop, walls "soft") | — |
| 4 OI / volume | 2 | OI concentration; flags strikes where **volume ≫ resting OI** (new positioning) | — |
| 5 Implied vol | 2 | IV term structure, 25Δ risk reversal, expected move; **"no edge" if target inside the implied move** | — |
| 6 Structure | 2 | Instrument from regime (neg γ → long options; pos γ → shares/spreads); entry near put wall, target into call wall, stop below put wall / gamma flip | hands off to sizing |

### Key formulas (implemented exactly)

```
gex_i      = gamma_i * oi_i * 100 * spot**2 * 0.01
net_gex    = sum(gex_calls) - sum(gex_puts)        # +ve => range; -ve => trend
value_growth_score = ps_ttm / revenue_growth_pct   # lower = more growth per $ of valuation
expected_move_$    = atm_call_price + atm_put_price # straddle bracketing the horizon
iv_term_structure  = front_atm_iv - back_atm_iv     # +ve => crush risk
risk_reversal_25d  = iv_put_25d - iv_call_25d        # +ve => downside demand
expectancy = win_rate*avg_win - loss_rate*avg_loss  # per setup bucket
```

## Risk profile / sizing rules ($2,000 book)

This build is configured for an **aggressive 10%-per-trade profile** (user-chosen, well above the conservative 0.75% the tool ships with by default). Change it in `swingdesk/config.py` (`BookRules`) or via `DEFAULT_RISK_PCT` in `.env`.

- Risk/trade = **10%** default ($200), slider band **1–20%** — the amount lost if stopped out, **not** the position size.
- Shares: `qty = floor(risk_$ / (entry − stop))`. Options: `contracts = floor(risk_$ / (premium·100))`.
- **No-margin buying-power cap:** position dollars can never exceed the account. At 10% risk with a tight stop the risk-based count can imply a position several times the account — it's capped to cash and the card honestly shows the *actual* (smaller) risk.
- When a single option contract exceeds the budget it's **surfaced honestly** ("1 contract = $X = Y% of book, exceeds budget") with alternatives, never silently rounded.
- Per-position cap **≤ 10% ($200)**; portfolio heat cap **≤ 40% ($800)** (~4 concurrent); **binary-event haircut halves** risk across an earnings/FDA/Fed print. (Caps scale with the risk setting.)

## Discipline gates (not optional)

- **Pre-mortem required** before any sizing card renders: bear case + invalidation evidence + historical base rate.
- **Expected-move flag:** target inside the implied move → "no edge" banner.
- **Correlation warning:** new ticker shares sector with an open position → "one bet sized up."
- **OPEX / macro flag:** hold window crosses OPEX/FOMC/CPI → re-read the regime on the far side of OPEX.

## Journal & expectancy

SQLite (`data/journal.db`). Logs ticker, setup/catalyst, direction, instrument, entry-regime tag, entry/stop/target, size, risk, implied vs realized move, outcome, P/L, and the pre-mortem text. Expectancy is computed **per setup bucket**; every figure shows its trade count and anything under ~30 trades is labeled **"not yet significant."**

## Architecture

```
app.py                     Streamlit cockpit (Morning · Analyze · Positions · Journal), dark theme
refresh.py                 morning refresh entry point (launchd / manual)
swingdesk/
  config.py                book rules, risk constants, .env key access
  models.py                typed dataclasses (Quote, OptionChain, GexProfile, ...)
  greeks.py                Black-Scholes gamma/delta (vol_surface conventions)
  gex.py                   local GEX: net GEX, gamma flip, walls
  calendar_util.py         3rd-Friday OPEX + FOMC/CPI loader
  analysis.py              the funnel — Stages 0-6, gate-on-fail
  sizing.py                risk-based sizing, caps, heat, binary haircut, buying-power cap
  discipline.py            pre-mortem gate + flags
  journal.py               SQLite journal + expectancy
  snapshot.py              daily snapshot: watchlist scan + open-position re-read
  oi_cache.py              free pre-market OI cache (capture live OI, backfill off-hours)
  viz.py                   dark Plotly: GEX-by-strike + OI/volume
  providers/               swappable data layer (yfinance, Tradier, Finnhub, FlashAlpha, demo, fallback, registry)
scripts/install_launchd.sh / uninstall_launchd.sh   morning auto-refresh agent
data/watchlist.json        tickers pulled each morning (edit in-app too)
data/fomc_cpi_dates.json   maintained macro list (verify against fed/BLS schedules)
data/snapshots/            dated daily snapshots (latest.pkl + latest.json)
tests/                     pytest suite (no network)
```

Providers sit behind ABCs (`providers/base.py`) so you can swap yfinance → Tradier/Polygon, or local GEX → a hosted source, without touching the analysis engine.

"""Console entry points. Installed as the `swingdesk-refresh` command; also used
by the root `refresh.py` wrapper and the launchd agent.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import Optional


def refresh_main(argv: Optional[list[str]] = None) -> int:
    """Pull the watchlist + open positions and save a daily snapshot."""
    ap = argparse.ArgumentParser(prog="swingdesk-refresh", description="swingdesk daily refresh")
    ap.add_argument("--demo", action="store_true", help="use synthetic demo data (no network)")
    args = ap.parse_args(argv)

    start = datetime.now()
    print(f"[{start.isoformat(timespec='seconds')}] swingdesk refresh starting (demo={args.demo})")
    try:
        from .snapshot import run_refresh
        snap = run_refresh(demo=args.demo or None)
    except Exception as e:  # noqa: BLE001
        print(f"  FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    ok = list(snap.results)
    passed = [t for t, r in snap.results.items() if r.passed]
    share_only = [t for t, r in snap.results.items() if r.share_only]
    print(f"  as of {snap.as_of}  (book ${snap.book_size:,.0f}, risk {snap.risk_pct*100:.0f}%/trade)")
    print(f"  watchlist: {len(ok)}/{len(snap.watchlist)} ok" + (f"; errors: {list(snap.errors)}" if snap.errors else ""))
    print(f"  passed funnel: {passed}")
    print(f"  share-only:    {share_only}")
    print(f"  open positions updated: {len(snap.positions)}")
    flipped = [p.ticker for p in snap.positions if p.regime_flipped]
    if flipped:
        print(f"  ⚠ regime FLIPPED since entry: {flipped}")
    print(f"  done in {(datetime.now() - start).total_seconds():.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(refresh_main())

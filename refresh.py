#!/usr/bin/env python3
"""Morning refresh — thin wrapper so `python refresh.py [--demo]` keeps working
(used by the launchd agent). The implementation lives in swingdesk/cli.py and is
also installed as the `swingdesk-refresh` command.

    python refresh.py            # live providers (yfinance + any keys in .env)
    python refresh.py --demo     # synthetic demo data (no network)
"""
from __future__ import annotations

import sys

from swingdesk.cli import refresh_main

if __name__ == "__main__":
    sys.exit(refresh_main())

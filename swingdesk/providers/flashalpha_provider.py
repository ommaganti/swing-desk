"""FlashAlpha GEX provider — optional hosted CROSS-CHECK of the local GEX.

Free tier: 5 GEX requests/day, no credit card. Needs FLASHALPHA_API_KEY.
This is a sanity check on the locally-computed call wall / put wall / gamma flip,
NOT the source of truth — local compute always runs regardless.

NOTE ON THE ENDPOINT: FlashAlpha's exact path and JSON field names can change
(see https://flashalpha.com/docs/lab-api-gex). This adapter is intentionally
defensive — it reads the base URL / path from the env, maps several likely field
names, and returns None on ANY mismatch or error so local GEX silently stands.
If the hosted numbers don't appear in the UI, verify FLASHALPHA_BASE_URL /
FLASHALPHA_GEX_PATH against the current docs.
"""
from __future__ import annotations

import os
from typing import Optional

import pandas as pd
import requests

from ..config import get_key
from ..models import GexProfile
from .base import GexProvider

_DEFAULT_BASE = "https://api.flashalpha.com"
_DEFAULT_PATH = "/v1/gex"  # verify against current FlashAlpha docs


def _first(d: dict, *keys, default=None):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


class FlashAlphaProvider(GexProvider):
    source = "FlashAlpha (hosted GEX)"

    def __init__(self) -> None:
        self._key = get_key("flashalpha")
        if not self._key:
            raise RuntimeError("FlashAlphaProvider requires FLASHALPHA_API_KEY")
        self._base = os.getenv("FLASHALPHA_BASE_URL", _DEFAULT_BASE).rstrip("/")
        self._path = os.getenv("FLASHALPHA_GEX_PATH", _DEFAULT_PATH)

    def get_gex(self, symbol: str, spot: Optional[float] = None) -> Optional[GexProfile]:
        url = f"{self._base}{self._path}"
        try:
            r = requests.get(
                url,
                params={"symbol": symbol, "ticker": symbol},
                headers={"Authorization": f"Bearer {self._key}",
                         "X-API-Key": self._key},
                timeout=10,
            )
            r.raise_for_status()
            data = r.json()
        except Exception:
            return None  # fail soft: local GEX is the source of truth

        if not isinstance(data, dict):
            return None
        # Some APIs nest under "data"/"result".
        body = data.get("data") or data.get("result") or data

        try:
            net = _first(body, "net_gex", "netGex", "total_gex", "gex")
            call_wall = _first(body, "call_wall", "callWall", "call_resistance")
            put_wall = _first(body, "put_wall", "putWall", "put_support")
            flip = _first(body, "gamma_flip", "gammaFlip", "zero_gamma", "flip")
            sp = spot if spot is not None else _first(body, "spot", "price", "underlying")
        except Exception:
            return None

        if net is None and call_wall is None and put_wall is None and flip is None:
            return None  # nothing usable -> let local GEX stand

        net_f = float(net) if net is not None else 0.0
        return GexProfile(
            symbol=symbol,
            spot=float(sp) if sp is not None else (spot or 0.0),
            net_gex=net_f,
            regime="positive" if net_f > 0 else "negative",
            gamma_flip=float(flip) if flip is not None else None,
            call_wall=float(call_wall) if call_wall is not None else None,
            put_wall=float(put_wall) if put_wall is not None else None,
            by_strike=pd.DataFrame(columns=["strike", "call_gex", "put_gex", "net_gex", "cum_gex"]),
            source=self.source,
            is_delayed=True,
            is_soft=False,
            note="hosted cross-check",
        )

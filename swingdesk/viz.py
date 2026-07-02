"""Plotly figures — dark "Data-Dense Dashboard" theme (UI/UX skill design system).

The GEX-by-strike profile and the OI/volume chain view, themed to match the dark
cockpit: transparent backgrounds, low-contrast grid, Fira Code tick figures, and
the semantic status palette (green = positive gamma, coral = negative gamma).
"""
from __future__ import annotations

from typing import Optional

import plotly.graph_objects as go

POS_GREEN = "#22C55E"
NEG_CORAL = "#FB7185"
SPOT_LINE = "#E2E8F0"
FLIP_BLUE = "#60A5FA"
PUT_CORAL = "#FB7185"
GRID = "#222B40"
AXIS = "#94A3B8"
MONO = "Fira Code, ui-monospace, monospace"


def _dark(fig: go.Figure, title: str, x_title: str, y_title: str, height: int = 360) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(color="#E2E8F0", size=14)),
        xaxis_title=x_title, yaxis_title=y_title,
        height=height, margin=dict(l=10, r=10, t=44, b=10),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family=MONO, color=AXIS, size=11),
        showlegend=False,
    )
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID)
    return fig


def gex_profile_chart(gex) -> go.Figure:
    """Net GEX by strike, with spot / gamma-flip / call-wall / put-wall markers."""
    df = gex.by_strike
    fig = go.Figure()
    if not df.empty:
        colors = [POS_GREEN if v >= 0 else NEG_CORAL for v in df["net_gex"]]
        fig.add_bar(x=df["strike"], y=df["net_gex"], marker_color=colors, name="Net GEX",
                    hovertemplate="strike %{x}<br>net GEX %{y:,.0f}<extra></extra>")

    def vline(x: Optional[float], color: str, label: Optional[str], pos: str, dash: str = "dash") -> None:
        if x is None or label is None:
            return
        fig.add_vline(x=x, line_color=color, line_dash=dash, line_width=2,
                      annotation_text=label, annotation_position=pos,
                      annotation_font=dict(color=color, size=10))

    vline(gex.put_wall, PUT_CORAL, f"put wall {gex.put_wall:g}" if gex.put_wall else None, "bottom left")
    vline(gex.gamma_flip, FLIP_BLUE, f"flip {gex.gamma_flip:g}" if gex.gamma_flip else None, "bottom right")
    vline(gex.spot, SPOT_LINE, f"spot {gex.spot:g}", "top left", dash="solid")
    vline(gex.call_wall, POS_GREEN, f"call wall {gex.call_wall:g}" if gex.call_wall else None, "top right")

    return _dark(fig, f"{gex.symbol} — net GEX by strike ({gex.regime})", "strike",
                 "net gamma exposure", height=380)


def oi_volume_chart(ec, spot: float) -> go.Figure:
    """Calls (up) vs puts (down) open interest, with today's volume overlaid so
    'volume ≫ OI' new-positioning strikes pop out."""
    fig = go.Figure()
    c, p = ec.calls, ec.puts
    if c is not None and not c.empty:
        fig.add_bar(x=c["strike"], y=c["openInterest"], name="call OI", marker_color=POS_GREEN, opacity=0.75)
        fig.add_bar(x=c["strike"], y=c["volume"], name="call vol", marker_color=POS_GREEN, opacity=0.30)
    if p is not None and not p.empty:
        fig.add_bar(x=p["strike"], y=-p["openInterest"], name="put OI", marker_color=PUT_CORAL, opacity=0.75)
        fig.add_bar(x=p["strike"], y=-p["volume"], name="put vol", marker_color=PUT_CORAL, opacity=0.30)
    fig.add_vline(x=spot, line_color=SPOT_LINE, line_dash="solid", line_width=2,
                  annotation_text=f"spot {spot:g}", annotation_position="top",
                  annotation_font=dict(color=SPOT_LINE, size=10))
    fig = _dark(fig, f"{ec.expiry.isoformat()} — OI (solid) & volume (faded), calls ▲ / puts ▼",
                "strike", "contracts (calls + / puts −)", height=360)
    fig.update_layout(barmode="overlay", showlegend=True,
                      legend=dict(orientation="h", y=-0.18, font=dict(color=AXIS, size=10)))
    return fig

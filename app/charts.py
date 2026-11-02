"""Altair chart helpers with one consistent look.

Colours are the first three slots of a validated categorical palette (blue,
orange, aqua; worst colour-blind distance 9.2, normal-vision 24 in all pairs).
Colours are tied to the series name, never to its position, so a filter never
repaints a series. One y axis per chart, thin marks, recessive grid.
"""

from __future__ import annotations

import altair as alt
import pandas as pd

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
PALETTE = [BLUE, ORANGE, AQUA]
GRID = "#d9d9d4"
MUTED = "#8a8a85"


def _scale(domain: list[str]) -> alt.Scale:
    return alt.Scale(domain=domain, range=PALETTE[: len(domain)])


def _finish(chart, height: int):
    return (
        chart.properties(height=height)
        .configure_view(stroke=None)
        .configure_axis(gridColor=GRID, gridOpacity=0.55, domain=False, tickSize=0, labelPadding=6, title=None)
        .configure_legend(orient="top", title=None, symbolStrokeWidth=3, labelFontSize=12, padding=0)
    )


def _x(field: str, weekly: bool = False, pad: int = 12) -> alt.X:
    axis = alt.Axis(format="%d %b", labelAngle=0, tickCount=6 if not weekly else "week", grid=False)
    return alt.X(f"{field}:T", axis=axis, scale=alt.Scale(padding=pad))


def _rank(df: pd.DataFrame, series: str, order: list[str]) -> pd.DataFrame:
    """Numeric stacking order so segments always stack in the order given."""
    frame = df.copy()
    frame["_rank"] = frame[series].map({name: i for i, name in enumerate(order)})
    return frame


def _target_layer(value: float, label: str, fmt: str):
    frame = pd.DataFrame({"y": [value], "label": [label]})
    rule = alt.Chart(frame).mark_rule(strokeDash=[5, 4], color=MUTED, strokeWidth=1).encode(y="y:Q")
    text = (
        alt.Chart(frame)
        .mark_text(align="left", dx=4, dy=-6, color=MUTED, fontSize=11)
        .encode(y="y:Q", text="label:N", x=alt.value(0))
    )
    return rule + text


def line(
    df: pd.DataFrame, x: str, y: str, *, series: str | None = None, order: list[str] | None = None,
    fmt: str = ",.0f", height: int = 260, weekly: bool = False, target: float | None = None,
    target_label: str = "", zero: bool = False,
):
    """Lines over time. `series` makes one line per value, coloured by name."""
    y_enc = alt.Y(f"{y}:Q", axis=alt.Axis(format=fmt), scale=alt.Scale(zero=zero, nice=True, padding=0 if zero else 14))
    tooltip = [alt.Tooltip(f"{x}:T", title="Date", format="%d %b %Y"), alt.Tooltip(f"{y}:Q", title=y, format=fmt)]
    if series:
        domain = order or sorted(df[series].unique())
        color = alt.Color(f"{series}:N", scale=_scale(domain), legend=alt.Legend(orient="top"))
        tooltip.insert(1, alt.Tooltip(f"{series}:N", title="Series"))
        base = alt.Chart(df).encode(x=_x(x, weekly), y=y_enc, color=color, tooltip=tooltip)
    else:
        base = alt.Chart(df).encode(x=_x(x, weekly), y=y_enc, color=alt.value(BLUE), tooltip=tooltip)

    chart = base.mark_line(strokeWidth=2, interpolate="monotone") + base.mark_point(size=70, filled=True, opacity=0 if not weekly else 1)
    if target is not None:
        chart = chart + _target_layer(target, target_label, fmt)
    return _finish(chart, height)


def bars(
    df: pd.DataFrame, category: str, value: str, *, fmt: str = ",.1f", order: list[str] | None = None,
    height: int = 240, color: str = BLUE, labels: bool = True, y_max: float | None = None,
):
    """Vertical bars with a rounded data end and the value above each bar."""
    x = alt.X(f"{category}:N", sort=order, axis=alt.Axis(labelAngle=0, grid=False))
    y = alt.Y(f"{value}:Q", axis=alt.Axis(format=fmt, grid=True), scale=alt.Scale(zero=True, domain=[0, y_max] if y_max else alt.Undefined))
    base = alt.Chart(df).encode(
        x=x, y=y, tooltip=[alt.Tooltip(f"{category}:N"), alt.Tooltip(f"{value}:Q", format=fmt)],
    )
    chart = base.mark_bar(color=color, cornerRadiusTopLeft=4, cornerRadiusTopRight=4, size=34)
    if labels:
        chart = chart + base.mark_text(dy=-8, fontSize=12).encode(text=alt.Text(f"{value}:Q", format=fmt))
    return _finish(chart, height)


def stacked_bars(
    df: pd.DataFrame, x: str, value: str, series: str, *, order: list[str], fmt: str = ",.0f",
    height: int = 260, normalize: bool = False,
):
    """Stacked bars with a thin gap between segments."""
    y = alt.Y(f"{value}:Q", stack="normalize" if normalize else "zero", axis=alt.Axis(format="%" if normalize else fmt))
    chart = (
        alt.Chart(_rank(df, series, order))
        .mark_bar(stroke="white", strokeWidth=1.5, size=26)
        .encode(
            x=_x(x, weekly=True, pad=34), y=y,
            color=alt.Color(f"{series}:N", scale=_scale(order), legend=alt.Legend(orient="top")),
            order=alt.Order("_rank:Q", sort="ascending"),
            tooltip=[alt.Tooltip(f"{x}:T", title="Week of", format="%d %b %Y"), alt.Tooltip(f"{series}:N"),
                     alt.Tooltip(f"{value}:Q", format=fmt)],
        )
    )
    return _finish(chart, height)


def stacked_area(df: pd.DataFrame, x: str, value: str, series: str, *, order: list[str], fmt: str = ",.0f", height: int = 260):
    chart = (
        alt.Chart(_rank(df, series, order))
        .mark_area(opacity=0.9, line={"strokeWidth": 1.5})
        .encode(
            x=_x(x, pad=0), y=alt.Y(f"{value}:Q", stack="zero", axis=alt.Axis(format=fmt)),
            color=alt.Color(f"{series}:N", scale=_scale(order), legend=alt.Legend(orient="top")),
            order=alt.Order("_rank:Q", sort="ascending"),
            tooltip=[alt.Tooltip(f"{x}:T", title="Date", format="%d %b %Y"), alt.Tooltip(f"{series}:N"),
                     alt.Tooltip(f"{value}:Q", format=fmt)],
        )
    )
    return _finish(chart, height)

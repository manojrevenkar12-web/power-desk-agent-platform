"""Expected answers, computed a second time, independently of powerdesk.quant.

The quant library is what the tools run; this module re-implements each metric from the raw
market frame in plain pandas, so an eval that passes means two implementations agree with the
answer the agent gave, not that the tool agrees with itself. Battery optima are not
re-implemented and are not checked numerically.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

import numpy as np
import pandas as pd

from powerdesk.market.model import build
from powerdesk.settings import book, market

TZ = "Europe/Berlin"


def _frame(zone: str, start: str, end: str) -> pd.DataFrame:
    df = build()
    df = df[df["zone"] == zone].copy()
    df["local"] = df["ts"].dt.tz_convert(TZ)
    day = df["local"].dt.date
    return df[(day >= date.fromisoformat(start)) & (day < date.fromisoformat(end))]


def _peak(df: pd.DataFrame) -> pd.Series:
    loc = df["local"]
    return (loc.dt.weekday < 5) & (loc.dt.hour >= 8) & (loc.dt.hour < 20)


def average_price(zone: str, start: str, end: str, product: str = "base", kind: str = "day_ahead") -> float:
    df = _frame(zone, start, end)
    col = {"day_ahead": "da_price", "intraday": "id_price", "imbalance": "imbalance_price"}[kind]
    if product == "peak":
        df = df[_peak(df)]
    elif product == "offpeak":
        df = df[~_peak(df)]
    return float(df[col].sum() / len(df))


def min_price(zone: str, start: str, end: str) -> float:
    return float(_frame(zone, start, end)["da_price"].min())


def max_price(zone: str, start: str, end: str) -> float:
    return float(_frame(zone, start, end)["da_price"].max())


def negative_hours(zone: str, start: str, end: str) -> float:
    return float((_frame(zone, start, end)["da_price"] < 0).sum()) / 4


def _gen(df: pd.DataFrame, tech: str) -> pd.Series:
    if tech == "wind":
        return df["wind_onshore_mw"] + df["wind_offshore_mw"]
    return df[f"{tech}_mw"]


def capture_price(zone: str, start: str, end: str, technology: str = "solar") -> float:
    df = _frame(zone, start, end)
    g = _gen(df, technology)
    return float(np.dot(g, df["da_price"]) / g.sum())


def capture_rate(zone: str, start: str, end: str, technology: str = "solar") -> float:
    return 100 * capture_price(zone, start, end, technology) / average_price(zone, start, end)


def _ppa_series(ppa_id: str, start: str, end: str) -> tuple[pd.Series, pd.Series, float]:
    p = book().ppas[ppa_id]
    s = max(start, p.start)
    e = min(end, (date.fromisoformat(p.end) + timedelta(days=1)).isoformat())
    df = _frame(p.zone, s, e)
    z = market().zones[p.zone]
    cap = {"solar": z.solar_gw, "wind_onshore": z.wind_onshore_gw, "wind_offshore": z.wind_offshore_gw}[p.tech] * 1000
    mwh = _gen(df, p.tech) / cap * p.mw / 4
    price = df["da_price"]
    if p.negative_clause:
        mwh = mwh.where(price >= 0, 0.0)
    return mwh, price, p.strike


def ppa_volume(ppa: str, start: str, end: str) -> float:
    return float(_ppa_series(ppa, start, end)[0].sum())


def ppa_pnl(ppa: str, start: str, end: str) -> float:
    mwh, price, strike = _ppa_series(ppa, start, end)
    return float((mwh * (price - strike)).sum())


def ppa_capture_price(ppa: str, start: str, end: str) -> float:
    mwh, price, _ = _ppa_series(ppa, start, end)
    return float((mwh * price).sum() / mwh.sum())


def portfolio_pnl(books: list[str], start: str, end: str) -> float:
    total = 0.0
    for pid, p in book().ppas.items():
        if p.book in books and p.start < end and (date.fromisoformat(p.end) + timedelta(days=1)).isoformat() > start:
            total += ppa_pnl(pid, start, end)
    return total


def hedge_total_pnl(books: list[str], month: str) -> float:
    y, m = (int(x) for x in month.split("-"))
    start = date(y, m, 1).isoformat()
    end = date(y + (m == 12), m % 12 + 1, 1).isoformat()
    total = 0.0
    for h in book().hedges:
        if h.book in books and h.month == month:
            df = _frame(h.zone, start, end)
            if h.product == "peak":
                df = df[_peak(df)]
            total += h.mw * (len(df) / 4) * (df["da_price"].mean() - h.price)
    return total


METRICS: dict[str, Callable[..., float]] = {
    "average_price": average_price,
    "min_price": min_price,
    "max_price": max_price,
    "negative_hours": negative_hours,
    "capture_price": capture_price,
    "capture_rate": capture_rate,
    "ppa_volume": ppa_volume,
    "ppa_pnl": ppa_pnl,
    "ppa_capture_price": ppa_capture_price,
    "portfolio_pnl": portfolio_pnl,
    "hedge_total_pnl": hedge_total_pnl,
}


def expected(spec: dict) -> float:
    args = {k: v for k, v in spec.items() if k != "metric"}
    return METRICS[spec["metric"]](**args)

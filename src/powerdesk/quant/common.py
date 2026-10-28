"""Shared pieces of the quant library: periods, products and rounding.

The desk thinks in local delivery days (CET/CEST); data is stored in UTC. Every function takes a
period as local dates, inclusive of `start` and exclusive of `end`, like delivery periods.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from powerdesk.market.model import zone_frame
from powerdesk.settings import market

LOCAL_TZ = "Europe/Berlin"
MTU_HOURS = 0.25


class QuantError(ValueError):
    """A request the library cannot answer as asked (unknown zone, empty period, ...)."""


@dataclass(frozen=True)
class Period:
    start: date
    end: date  # exclusive

    @classmethod
    def parse(cls, start: str, end: str) -> Period:
        try:
            p = cls(date.fromisoformat(start), date.fromisoformat(end))
        except ValueError as e:
            raise QuantError(f"dates must be YYYY-MM-DD: {e}") from e
        if p.end <= p.start:
            raise QuantError("end must be after start (end is exclusive)")
        m = market()
        first = pd.Timestamp(m.start).tz_convert(LOCAL_TZ).date()
        last = (pd.Timestamp(m.end) - pd.Timedelta(minutes=m.mtu_minutes)).tz_convert(LOCAL_TZ).date()
        if p.start < first or p.end > date.fromordinal(last.toordinal() + 1):
            raise QuantError(f"data covers delivery days {first} to {last}")
        return p

    @classmethod
    def month(cls, month: str) -> Period:
        y, m = (int(x) for x in month.split("-"))
        end = date(y + (m == 12), m % 12 + 1, 1)
        return cls.parse(date(y, m, 1).isoformat(), end.isoformat())

    def utc_bounds(self) -> tuple[pd.Timestamp, pd.Timestamp]:
        s = pd.Timestamp(self.start).tz_localize(LOCAL_TZ).tz_convert("UTC")
        e = pd.Timestamp(self.end).tz_localize(LOCAL_TZ).tz_convert("UTC")
        return s, e

    def as_dict(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end_exclusive": self.end.isoformat()}


def window(zone: str, p: Period) -> pd.DataFrame:
    try:
        df = zone_frame(zone)
    except KeyError as e:
        raise QuantError(f"unknown zone {zone}; zones are {', '.join(market().zones)}") from e
    lo, hi = p.utc_bounds()
    w = df[(df.index >= lo) & (df.index < hi)]
    if w.empty:
        raise QuantError("no data in that period")
    return w


def is_peak(index: pd.DatetimeIndex) -> pd.Series:
    """Peak load: 08:00-20:00 local on weekdays (EEX definition)."""
    local = index.tz_convert(LOCAL_TZ)
    return pd.Series((local.dayofweek < 5) & (local.hour >= 8) & (local.hour < 20), index=index)


def local_str(ts: pd.Timestamp) -> str:
    return ts.tz_convert(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")


def r2(x: float) -> float:
    return round(float(x), 2)


def r0(x: float) -> float:
    return float(round(float(x)))

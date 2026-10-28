"""Market questions a desk asks every day: price statistics, negative prices, capture prices and
what drove a price. All prices are EUR/MWh, energy MWh, power MW."""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

from powerdesk.quant.common import MTU_HOURS, Period, QuantError, is_peak, local_str, r0, r2, window

PriceKind = Literal["day_ahead", "intraday", "imbalance"]
Product = Literal["base", "peak", "offpeak"]
GenTech = Literal["solar", "wind_onshore", "wind_offshore", "wind"]

_COL = {"day_ahead": "da_price", "intraday": "id_price", "imbalance": "imbalance_price"}


def _select(w: pd.DataFrame, product: Product) -> pd.DataFrame:
    peak = is_peak(w.index)
    if product == "peak":
        return w[peak.to_numpy()]
    if product == "offpeak":
        return w[~peak.to_numpy()]
    return w


def price_stats(zone: str, start: str, end: str, kind: PriceKind = "day_ahead", product: Product = "base") -> dict:
    p = Period.parse(start, end)
    w = _select(window(zone, p), product)
    if w.empty:
        raise QuantError(f"no {product} intervals in that period")
    s = w[_COL[kind]]
    return {
        "zone": zone,
        "period": p.as_dict(),
        "kind": kind,
        "product": product,
        "average": r2(s.mean()),
        "minimum": r2(s.min()),
        "minimum_at": local_str(s.idxmin()),
        "maximum": r2(s.max()),
        "maximum_at": local_str(s.idxmax()),
        "standard_deviation": r2(s.std(ddof=0)),
        "intervals": len(s),
        "units": {"average": "EUR/MWh", "minimum": "EUR/MWh", "maximum": "EUR/MWh", "standard_deviation": "EUR/MWh", "intervals": "count"},
    }


def negative_prices(zone: str, start: str, end: str) -> dict:
    """Negative day-ahead quarter hours. Since the 2025 EEG amendment (s.51), plants commissioned
    after 25 Feb 2025 get no market premium in any negative 15-minute interval."""
    p = Period.parse(start, end)
    w = window(zone, p)
    neg = (w["da_price"] < 0).to_numpy()
    runs: list[int] = []
    n = 0
    for v in neg:
        if v:
            n += 1
        elif n:
            runs.append(n)
            n = 0
    if n:
        runs.append(n)
    local = w.index.tz_convert("Europe/Berlin")
    by_month = pd.Series(neg, index=local).groupby(local.strftime("%Y-%m")).sum()
    return {
        "zone": zone,
        "period": p.as_dict(),
        "negative_intervals": int(neg.sum()),
        "negative_hours": r2(neg.sum() * MTU_HOURS),
        "share_of_intervals": r2(100 * neg.mean()),
        "longest_run_hours": r2(max(runs, default=0) * MTU_HOURS),
        "lowest_price": r2(w["da_price"].min()),
        "by_month_hours": {k: r2(v * MTU_HOURS) for k, v in by_month.items()},
        "units": {"negative_intervals": "count", "negative_hours": "h", "share_of_intervals": "%", "longest_run_hours": "h", "lowest_price": "EUR/MWh", "by_month_hours": "h"},
    }


def generation(w: pd.DataFrame, tech: GenTech) -> pd.Series:
    if tech == "wind":
        return w["wind_onshore_mw"] + w["wind_offshore_mw"]
    return w[f"{tech}_mw"]


def capture_price(zone: str, tech: GenTech, start: str, end: str) -> dict:
    """Generation-weighted average day-ahead price a technology earned, against the baseload average."""
    p = Period.parse(start, end)
    w = window(zone, p)
    g = generation(w, tech)
    if g.sum() <= 0:
        raise QuantError(f"no {tech} generation in that period")
    price = w["da_price"]
    capture = float((g * price).sum() / g.sum())
    base = float(price.mean())
    neg_share = float(g[price < 0].sum() / g.sum())
    return {
        "zone": zone,
        "technology": tech,
        "period": p.as_dict(),
        "capture_price": r2(capture),
        "baseload_price": r2(base),
        "capture_rate": r2(100 * capture / base) if base else None,
        "generation_twh": round(float(g.sum() * MTU_HOURS / 1e6), 3),
        "generation_in_negative_hours": r2(100 * neg_share),
        "units": {"capture_price": "EUR/MWh", "baseload_price": "EUR/MWh", "capture_rate": "%", "generation_twh": "TWh", "generation_in_negative_hours": "%"},
    }


def price_drivers(zone: str, start: str, end: str) -> dict:
    """Why prices were where they were: residual load, renewables, fuel and the price-setting block,
    and the lowest and highest quarter hours with their drivers."""
    p = Period.parse(start, end)
    w = window(zone, p)
    res = (w["solar_fc_mw"] + w["wind_fc_mw"]) / 1000
    corr = float(np.corrcoef(w["residual_fc_mw"], w["da_price"])[0, 1]) if len(w) > 2 else 0.0
    setters = (w["price_setter"].value_counts(normalize=True) * 100).round(1)

    def moment(ts: pd.Timestamp) -> dict:
        row = w.loc[ts]
        return {
            "at": local_str(ts),
            "price": r2(row["da_price"]),
            "residual_load_gw": round(float(row["residual_fc_mw"]) / 1000, 1),
            "renewables_forecast_gw": round(float(row["solar_fc_mw"] + row["wind_fc_mw"]) / 1000, 1),
            "demand_forecast_gw": round(float(row["demand_fc_mw"]) / 1000, 1),
            "price_setter": row["price_setter"],
        }

    return {
        "zone": zone,
        "period": p.as_dict(),
        "average_price": r2(w["da_price"].mean()),
        "average_residual_load_gw": round(float(w["residual_fc_mw"].mean()) / 1000, 1),
        "average_renewables_forecast_gw": round(float(res.mean()), 1),
        "residual_load_price_correlation": round(corr, 2),
        "gas_ttf": r2(w["ttf"].mean()),
        "carbon_eua": r2(w["eua"].mean()),
        "price_setter_share": {str(k): float(v) for k, v in setters.items()},
        "lowest": moment(w["da_price"].idxmin()),
        "highest": moment(w["da_price"].idxmax()),
        "units": {
            "average_price": "EUR/MWh",
            "average_residual_load_gw": "GW",
            "average_renewables_forecast_gw": "GW",
            "residual_load_price_correlation": "ratio",
            "gas_ttf": "EUR/MWh",
            "carbon_eua": "EUR/t",
            "price_setter_share": "%",
            "price": "EUR/MWh",
            "residual_load_gw": "GW",
            "renewables_forecast_gw": "GW",
            "demand_forecast_gw": "GW",
        },
    }


def forecast_error(zone: str, tech: GenTech, start: str, end: str) -> dict:
    """Day-ahead forecast error of a technology: bias, mean absolute error, worst miss."""
    p = Period.parse(start, end)
    w = window(zone, p)
    actual = generation(w, tech)
    fc = w["wind_fc_mw"] if tech.startswith("wind") else w["solar_fc_mw"]
    if tech in ("wind_onshore", "wind_offshore"):
        share = actual / (w["wind_onshore_mw"] + w["wind_offshore_mw"]).replace(0, np.nan)
        fc = fc * share.fillna(0)
    err = fc - actual
    worst = err.abs().idxmax()
    return {
        "zone": zone,
        "technology": tech,
        "period": p.as_dict(),
        "bias_mw": r0(err.mean()),
        "mean_absolute_error_mw": r0(err.abs().mean()),
        "worst_miss_mw": r0(err.loc[worst]),
        "worst_miss_at": local_str(worst),
        "units": {"bias_mw": "MW", "mean_absolute_error_mw": "MW", "worst_miss_mw": "MW"},
    }

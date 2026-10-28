"""The desk's own book: PPA valuation, imbalance exposure, battery backtests and hedges.

Callers decide who may see which book (powerdesk.policy); these functions only compute.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import linprog

from powerdesk.quant.common import MTU_HOURS, Period, QuantError, is_peak, r0, r2, window
from powerdesk.settings import Ppa, book, market


def _ppa(ppa_id: str) -> Ppa:
    p = book().ppas.get(ppa_id)
    if p is None:
        raise QuantError(f"unknown PPA {ppa_id}")
    return p


def _plant(ppa: Ppa, w: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """A plant's output and its day-ahead forecast, in MW: the zone fleet's capacity factor x plant size."""
    z = market().zones[ppa.zone]
    if ppa.tech == "solar":
        cap, act, fc = z.solar_gw * 1000, w["solar_mw"], w["solar_fc_mw"]
    else:
        col = f"{ppa.tech}_mw"
        cap = (z.wind_onshore_gw if ppa.tech == "wind_onshore" else z.wind_offshore_gw) * 1000
        act = w[col]
        share = act / (w["wind_onshore_mw"] + w["wind_offshore_mw"]).replace(0, np.nan)
        fc = w["wind_fc_mw"] * share.fillna(0)
    return act / cap * ppa.mw, fc / cap * ppa.mw


def _active(ppa: Ppa, p: Period) -> Period:
    s = max(p.start.isoformat(), ppa.start)
    e = min(p.end.isoformat(), (pd.Timestamp(ppa.end) + pd.Timedelta(days=1)).date().isoformat())
    if e <= s:
        raise QuantError("the PPA does not deliver in that period")
    return Period.parse(s, e)


def ppa_valuation(ppa_id: str, start: str, end: str) -> dict:
    """The desk buys the plant's output at the strike and sells it day-ahead. Pay-as-produced; with a
    negative-price clause no energy is delivered or paid in negative quarter hours."""
    ppa = _ppa(ppa_id)
    p = _active(ppa, Period.parse(start, end))
    w = window(ppa.zone, p)
    out, fc = _plant(ppa, w)
    price = w["da_price"]
    if ppa.negative_clause:
        curtailed = float((out[price < 0]).sum() * MTU_HOURS)
        out = out.where(price >= 0, 0.0)
        fc = fc.where(price >= 0, 0.0)
    else:
        curtailed = 0.0
    vol = out * MTU_HOURS
    volume = float(vol.sum())
    if volume <= 0:
        raise QuantError("no delivered volume in that period")
    market_value = float((vol * price).sum())
    cost = volume * ppa.strike
    capture = market_value / volume
    base = float(price.mean())
    imb = float(-((out - fc) * MTU_HOURS * (w["imbalance_price"] - price)).sum())
    return {
        "ppa": ppa_id,
        "book": ppa.book,
        "zone": ppa.zone,
        "technology": ppa.tech,
        "period": p.as_dict(),
        "strike": ppa.strike,
        "volume_mwh": r0(volume),
        "capture_price": r2(capture),
        "baseload_price": r2(base),
        "shape_discount": r2(base - capture),
        "market_value_eur": r0(market_value),
        "pnl_eur": r0(market_value - cost),
        "pnl_per_mwh": r2((market_value - cost) / volume),
        "curtailed_by_negative_clause_mwh": r0(curtailed),
        "imbalance_cost_eur": r0(imb),
        "units": {
            "strike": "EUR/MWh",
            "volume_mwh": "MWh",
            "capture_price": "EUR/MWh",
            "baseload_price": "EUR/MWh",
            "shape_discount": "EUR/MWh",
            "market_value_eur": "EUR",
            "pnl_eur": "EUR",
            "pnl_per_mwh": "EUR/MWh",
            "curtailed_by_negative_clause_mwh": "MWh",
            "imbalance_cost_eur": "EUR",
        },
    }


def ppa_portfolio(books: list[str], start: str, end: str) -> dict:
    """All PPAs in the given books (the caller passes only books the user may see)."""
    rows: list[dict[str, Any]] = []
    for pid, ppa in sorted(book().ppas.items()):
        if ppa.book not in books:
            continue
        try:
            rows.append(ppa_valuation(pid, start, end))
        except QuantError:
            continue
    if not rows:
        raise QuantError("no PPA delivers in those books and that period")
    vol = sum(r["volume_mwh"] for r in rows)
    return {
        "books": sorted(set(books)),
        "period": Period.parse(start, end).as_dict(),
        "ppas": [{k: r[k] for k in ("ppa", "book", "zone", "technology", "volume_mwh", "capture_price", "pnl_eur")} for r in rows],
        "total_volume_mwh": r0(vol),
        "total_pnl_eur": r0(sum(r["pnl_eur"] for r in rows)),
        "total_imbalance_cost_eur": r0(sum(r["imbalance_cost_eur"] for r in rows)),
        "volume_weighted_capture_price": r2(sum(r["capture_price"] * r["volume_mwh"] for r in rows) / vol),
        "units": {
            "volume_mwh": "MWh",
            "capture_price": "EUR/MWh",
            "pnl_eur": "EUR",
            "total_volume_mwh": "MWh",
            "total_pnl_eur": "EUR",
            "total_imbalance_cost_eur": "EUR",
            "volume_weighted_capture_price": "EUR/MWh",
        },
    }


def imbalance_exposure(ppa_id: str, start: str, end: str, extra_error_pct: float = 0.0) -> dict:
    """What forecast errors cost at imbalance prices, as delivered, and if the forecast had been off
    by an extra share of output in the direction that hurts (a stress, not a forecast)."""
    ppa = _ppa(ppa_id)
    p = _active(ppa, Period.parse(start, end))
    w = window(ppa.zone, p)
    out, fc = _plant(ppa, w)
    spread = w["imbalance_price"] - w["da_price"]
    realised = float(-((out - fc) * MTU_HOURS * spread).sum())
    stress = float((out * extra_error_pct / 100 * MTU_HOURS * spread.abs()).sum())
    return {
        "ppa": ppa_id,
        "book": ppa.book,
        "period": p.as_dict(),
        "realised_imbalance_cost_eur": r0(realised),
        "stress_extra_error_pct": extra_error_pct,
        "stress_additional_cost_eur": r0(stress),
        "mean_absolute_spread": r2(spread.abs().mean()),
        "units": {"realised_imbalance_cost_eur": "EUR", "stress_extra_error_pct": "%", "stress_additional_cost_eur": "EUR", "mean_absolute_spread": "EUR/MWh"},
    }


def _battery_day_lp(prices: np.ndarray, mw: float, mwh: float, eta: float) -> float:
    """Perfect-foresight arbitrage for one day: charge c, discharge d, state of charge s, starting
    and ending half full. Linear programme solved with HiGHS."""
    n = len(prices)
    h = MTU_HOURS
    # variables: c[0..n), d[0..n), s[0..n)
    cost = np.concatenate([prices * h, -prices * h, np.zeros(n)])
    a_eq = np.zeros((n, 3 * n))
    b_eq = np.zeros(n)
    for t in range(n):
        a_eq[t, 2 * n + t] = 1
        if t > 0:
            a_eq[t, 2 * n + t - 1] = -1
        a_eq[t, t] = -eta * h
        a_eq[t, n + t] = h / eta
        b_eq[t] = mwh / 2 if t == 0 else 0
    end_row = np.zeros((1, 3 * n))
    end_row[0, 3 * n - 1] = 1
    bounds = [(0, mw)] * (2 * n) + [(0, mwh)] * n
    res = linprog(cost, A_eq=np.vstack([a_eq, end_row]), b_eq=np.append(b_eq, mwh / 2), bounds=bounds, method="highs")
    if res.status != 0:
        raise QuantError(f"battery optimisation failed: {res.message}")
    return float(-res.fun)


def _battery_day_simple(prices: np.ndarray, mw: float, mwh: float, eta: float) -> float:
    """What a simple daily rule earns: charge in the cheapest full-power window, discharge in the
    dearest window after it."""
    k = max(1, int(round(mwh / mw / MTU_HOURS)))
    if len(prices) < 2 * k:
        return 0.0
    avg = np.convolve(prices, np.ones(k) / k, mode="valid")
    best = 0.0
    for i in range(len(avg)):
        later = avg[i + k :]
        if later.size:
            # buy a full charge at the window's average, sell what survives the round trip
            gain = mw * k * MTU_HOURS * (later.max() * eta**2 - avg[i])
            best = max(best, gain)
    return best


def battery_backtest(asset: str, start: str, end: str) -> dict:
    b = book().batteries.get(asset)
    if b is None:
        raise QuantError(f"unknown battery {asset}")
    p = Period.parse(start, end)
    w = window(b.zone, p)
    eta = float(np.sqrt(b.round_trip))
    local_day = w.index.tz_convert("Europe/Berlin").date
    lp = simple = 0.0
    days = 0
    for _, g in w.groupby(local_day):
        prices = g["da_price"].to_numpy()
        lp += _battery_day_lp(prices, b.mw, b.mwh, eta)
        simple += _battery_day_simple(prices, b.mw, b.mwh, eta)
        days += 1
    return {
        "asset": asset,
        "book": b.book,
        "zone": b.zone,
        "period": p.as_dict(),
        "days": days,
        "perfect_foresight_revenue_eur": r0(lp),
        "simple_rule_revenue_eur": r0(simple),
        "simple_rule_share_of_optimum": r2(100 * simple / lp) if lp > 0 else None,
        "perfect_foresight_eur_per_mw_day": r2(lp / b.mw / days),
        "units": {"days": "count", "perfect_foresight_revenue_eur": "EUR", "simple_rule_revenue_eur": "EUR", "simple_rule_share_of_optimum": "%", "perfect_foresight_eur_per_mw_day": "EUR/MW/day"},
    }


def hedge_report(books: list[str], month: str) -> dict:
    """Month futures settled against the month's average day-ahead price, and how much of the same
    zone's expected PPA output the books have hedged."""
    p = Period.month(month)
    hedges = [h for h in book().hedges if h.book in books and h.month == month]
    if not hedges:
        raise QuantError("no hedges in those books for that month")
    rows: list[dict[str, Any]] = []
    for h in hedges:
        w = window(h.zone, p)
        sel = w[is_peak(w.index).to_numpy()] if h.product == "peak" else w
        settle = float(sel["da_price"].mean())
        hours = len(sel) * MTU_HOURS
        rows.append(
            {
                "book": h.book,
                "zone": h.zone,
                "product": h.product,
                "mw": h.mw,
                "trade_price": h.price,
                "settlement_price": r2(settle),
                "pnl_eur": r0(h.mw * hours * (settle - h.price)),
                "volume_mwh": r0(abs(h.mw) * hours),
            }
        )
    zones = sorted({r["zone"] for r in rows})
    ratio = {}
    for z in zones:
        gen = 0.0
        for pid, ppa in book().ppas.items():
            if ppa.zone == z and book().books[ppa.book].desk in {book().books[b].desk for b in books}:
                try:
                    gen += ppa_valuation(pid, p.start.isoformat(), p.end.isoformat())["volume_mwh"]
                except QuantError:
                    pass
        sold = sum(r["volume_mwh"] for r in rows if r["zone"] == z and r["mw"] < 0)
        ratio[z] = r2(100 * sold / gen) if gen else None
    return {
        "books": sorted(set(books)),
        "month": month,
        "hedges": rows,
        "total_pnl_eur": r0(sum(r["pnl_eur"] for r in rows)),
        "hedge_ratio_pct": ratio,
        "units": {"mw": "MW", "trade_price": "EUR/MWh", "settlement_price": "EUR/MWh", "pnl_eur": "EUR", "volume_mwh": "MWh", "total_pnl_eur": "EUR", "hedge_ratio_pct": "%"},
    }

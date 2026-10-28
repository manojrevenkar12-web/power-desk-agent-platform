"""A stylised fundamental model of three coupled-but-separate European bidding zones.

Weather drives wind and solar; day-ahead prices clear on forecasts against a thermal merit order
that moves with gas and carbon; in surplus, renewables curtail and prices go negative, deeper the
larger the surplus beyond what plants under EEG section 51 (no premium in negative 15-minute
intervals) give up at zero. Intraday and imbalance prices react to forecast errors.

It is synthetic and deterministic (seeded). The point is a market with the structure a desk reasons
about, so the agent platform's tools have something real-shaped to compute on.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import pandas as pd

from powerdesk.settings import Market, Zone, market

COLUMNS = [
    "ts",
    "zone",
    "demand_mw",
    "demand_fc_mw",
    "solar_mw",
    "solar_fc_mw",
    "wind_onshore_mw",
    "wind_offshore_mw",
    "wind_fc_mw",
    "residual_fc_mw",
    "da_price",
    "id_price",
    "imbalance_price",
    "system_imbalance_mw",
    "price_setter",
    "ttf",
    "eua",
]


@dataclass(frozen=True)
class Weather:
    cloud: np.ndarray  # per day, 0 clear .. 1 overcast
    wind_on: np.ndarray  # capacity factor per 15 min
    wind_off: np.ndarray


def _index(m: Market) -> pd.DatetimeIndex:
    return pd.date_range(m.start, m.end, freq=f"{m.mtu_minutes}min", inclusive="left", tz="UTC")


def _ar1(rng: np.random.Generator, n: int, phi: float, sd: float = 1.0) -> np.ndarray:
    eps = rng.normal(0.0, sd * np.sqrt(1 - phi**2), n)
    x = np.empty(n)
    x[0] = rng.normal(0.0, sd)
    for i in range(1, n):
        x[i] = phi * x[i - 1] + eps[i]
    return x


def _to_mtu(hourly: np.ndarray, steps_per_hour: int, n: int) -> np.ndarray:
    """Linear interpolation of an hourly series onto the 15-minute grid."""
    t_hours = np.arange(n) / steps_per_hour
    return np.interp(t_hours, np.arange(len(hourly)), hourly)


def _demand_shape(local_hour: np.ndarray, peak_to_mean: float) -> np.ndarray:
    h = local_hour
    raw = 0.6 * np.exp(-(((h - 11.0) / 3.5) ** 2)) + 0.55 * np.exp(-(((h - 19.5) / 2.2) ** 2)) - 0.5 * np.exp(-(((h - 3.5) / 3.0) ** 2))
    grid = np.linspace(0, 24, 97)[:-1]
    ref = 0.6 * np.exp(-(((grid - 11.0) / 3.5) ** 2)) + 0.55 * np.exp(-(((grid - 19.5) / 2.2) ** 2)) - 0.5 * np.exp(-(((grid - 3.5) / 3.0) ** 2))
    ref_c = ref - ref.mean()
    amp = (peak_to_mean - 1.0) / ref_c.max()
    return 1.0 + amp * (raw - ref.mean())


def _solar_shape(local_hour: np.ndarray, day_of_year: np.ndarray) -> np.ndarray:
    """Clear-sky shape: day length falls from about 16.3 h at midsummer to 12 h at the equinox."""
    # day 172 = 21 June; day 266 = 23 September
    length = 16.3 - (16.3 - 12.0) * np.clip((day_of_year - 172) / (266 - 172), -0.3, 1.2)
    sunrise = 13.4 - length / 2  # solar noon at about 13:24 CEST in Germany
    x = (local_hour - sunrise) / length
    return np.where((x > 0) & (x < 1), np.sin(np.pi * np.clip(x, 0, 1)) ** 1.3, 0.0)


def _weather(m: Market, rng: np.random.Generator, n: int, days: int, steps: int) -> dict[str, Weather]:
    w = m.weather
    common_cloud = _ar1(rng, days, w.cloud_ar)
    common_wind = _ar1(rng, n // steps + 2, w.wind_ar_hourly)
    out: dict[str, Weather] = {}
    for zone in m.zones:
        own_cloud = _ar1(rng, days, w.cloud_ar)
        cloud = 1 / (1 + np.exp(-(0.75 * common_cloud + 0.5 * own_cloud)))  # 0..1
        z_on = 0.7 * common_wind + 0.71 * _ar1(rng, len(common_wind), w.wind_ar_hourly)
        z_off = 0.8 * common_wind + 0.6 * _ar1(rng, len(common_wind), w.wind_ar_hourly)
        on = np.clip(w.wind_mean_cf_onshore * np.exp(0.8 * z_on - 0.32), 0.01, 0.92)
        off = np.clip(w.wind_mean_cf_offshore * np.exp(0.6 * z_off - 0.18), 0.02, 0.96)
        out[zone] = Weather(cloud=cloud, wind_on=_to_mtu(on, steps, n), wind_off=_to_mtu(off, steps, n))
    return out


def _supply_curve(z: Zone, ttf: np.ndarray, eua: np.ndarray) -> tuple[list[str], np.ndarray, np.ndarray]:
    """Blocks of the merit order: names, cumulative GW (static), marginal cost per day x block."""
    names = list(z.thermal)
    caps = np.array([z.thermal[k][0] for k in names])
    mc = np.stack([z.thermal[k][1] * ttf + z.thermal[k][2] * eua + z.thermal[k][3] for k in names], axis=1)
    order = np.argsort(mc.mean(axis=0))  # merit order by average cost over the period
    return [names[i] for i in order], np.cumsum(caps[order]), mc[:, order]


def _clear(z: Zone, residual_gw: np.ndarray, res_gw: np.ndarray, day: np.ndarray, ttf: np.ndarray, eua: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    names, cum, mc = _supply_curve(z, ttf, eua)
    price = np.empty_like(residual_gw)
    setter = np.empty(residual_gw.shape, dtype=object)
    pos = residual_gw > 0
    # thermal side: interpolate within the block the residual load lands in
    idx = np.searchsorted(cum, residual_gw[pos], side="left")
    over = idx >= len(cum)
    idx_c = np.minimum(idx, len(cum) - 1)
    start = np.where(idx_c > 0, cum[np.maximum(idx_c - 1, 0)], 0.0)
    width = cum[idx_c] - start
    frac = np.clip((residual_gw[pos] - start) / width, 0, 1)
    p = mc[day[pos], idx_c] + z.unit_span_eur * frac
    # scarcity: the last 8% of the stack
    tight = residual_gw[pos] / cum[-1]
    p = p + np.where(tight > 0.92, 2500 * (tight - 0.92) ** 2 / 0.08**2 * 0.1, 0.0)
    p = np.where(over, z.cap_eur_mwh, p)
    price[pos] = np.minimum(p, z.cap_eur_mwh)
    setter[pos] = np.where(over, "scarcity", np.array(names, dtype=object)[idx_c])
    # surplus: exports, storage and batteries absorb it first, at falling prices; then renewables
    # curtail, those under EEG s.51 at zero, the rest deeper the larger the surplus
    surplus = -residual_gw[~pos]
    in_sink = surplus <= z.sink_gw
    beyond = np.maximum(0.0, surplus - z.sink_gw)
    free = z.new_res_share * res_gw[~pos]
    deep = np.maximum(0.0, beyond - free)
    p_sink = z.sink_price_eur * (1 - surplus / z.sink_gw)
    p_zero = -0.01 - 0.49 * beyond / np.maximum(free, 1e-6)
    p_deep = -0.5 - z.curtail_slope_eur_per_gw * deep
    price[~pos] = np.maximum(np.where(in_sink, p_sink, np.where(deep > 0, p_deep, p_zero)), z.floor_eur_mwh)
    setter[~pos] = np.where(in_sink, "exports and storage", np.where(deep > 0, "renewables curtailing below zero", "renewables curtailing at zero"))
    return price, setter


@lru_cache
def build() -> pd.DataFrame:
    """The whole market dataset: one row per zone and 15-minute interval."""
    m = market()
    rng = np.random.default_rng(m.seed)
    idx = _index(m)
    n = len(idx)
    steps = 60 // m.mtu_minutes
    days = n // (24 * steps)
    local = idx + pd.Timedelta(hours=m.utc_offset_hours)
    local_hour = (local.hour + local.minute / 60).to_numpy(dtype=float)
    doy = np.asarray(local.dayofyear)
    weekend = np.asarray(local.dayofweek >= 5)
    day = np.asarray((idx - idx[0]) // pd.Timedelta(days=1))
    ttf = m.fuels.ttf_start_eur_mwh * np.exp(np.cumsum(rng.normal(0, m.fuels.ttf_daily_vol, days + 1)))
    eua = m.fuels.eua_start_eur_t * np.exp(np.cumsum(rng.normal(0, m.fuels.eua_daily_vol, days + 1)))
    weather = _weather(m, rng, n, days + 1, steps)
    w = m.weather
    frames = []
    for zone, z in m.zones.items():
        wx = weather[zone]
        solar_cf = w.solar_peak_cf * _solar_shape(local_hour, doy) * (1 - 0.7 * wx.cloud[day]) * (1 + rng.normal(0, 0.03, n))
        solar = np.clip(solar_cf, 0, 1) * z.solar_gw
        won = wx.wind_on * z.wind_onshore_gw
        woff = wx.wind_off * z.wind_offshore_gw
        # day-ahead forecasts: errors persist over hours
        err_w = _to_mtu(_ar1(rng, n // steps + 2, 0.9, w.forecast_error_sd_wind), steps, n) * (z.wind_onshore_gw + z.wind_offshore_gw)
        err_s = _to_mtu(_ar1(rng, n // steps + 2, 0.85, w.forecast_error_sd_solar), steps, n) * z.solar_gw * (solar > 0)
        wind_fc = np.clip(won + woff + err_w, 0, z.wind_onshore_gw + z.wind_offshore_gw)
        solar_fc = np.clip(solar + err_s, 0, z.solar_gw)
        demand = z.demand_mean_gw * _demand_shape(local_hour, z.demand_peak_to_mean) * np.where(weekend, z.weekend_factor, 1.0)
        demand = demand * (1 + rng.normal(0, 0.006, n))
        demand_fc = demand * (1 + _to_mtu(_ar1(rng, n // steps + 2, 0.9, w.demand_error_sd), steps, n))
        res_fc = solar_fc + wind_fc
        residual_fc = demand_fc - z.must_run_gw - res_fc
        da, setter = _clear(z, residual_fc, res_fc, day, ttf, eua)
        # intraday: a renewables shortfall or higher demand than forecast lifts prices
        shortfall = (res_fc - (solar + won + woff)) + (demand - demand_fc)
        idp = da + m.intraday.slope_eur_per_gw * shortfall + rng.normal(0, m.intraday.noise_eur, n)
        imb_gw = m.imbalance.untraded_share * shortfall
        imb = idp + np.sign(imb_gw) * (m.imbalance.base_spread_eur + m.imbalance.slope_eur_per_gw * np.abs(imb_gw))
        imb = np.clip(imb, m.imbalance.floor_eur_mwh, m.imbalance.cap_eur_mwh)
        frames.append(
            pd.DataFrame(
                {
                    "ts": idx,
                    "zone": zone,
                    "demand_mw": demand * 1000,
                    "demand_fc_mw": demand_fc * 1000,
                    "solar_mw": solar * 1000,
                    "solar_fc_mw": solar_fc * 1000,
                    "wind_onshore_mw": won * 1000,
                    "wind_offshore_mw": woff * 1000,
                    "wind_fc_mw": wind_fc * 1000,
                    "residual_fc_mw": residual_fc * 1000,
                    "da_price": np.round(da, 2),
                    "id_price": np.round(idp, 2),
                    "imbalance_price": np.round(imb, 2),
                    "system_imbalance_mw": imb_gw * 1000,
                    "price_setter": setter,
                    "ttf": np.round(ttf[day], 2),
                    "eua": np.round(eua[day], 2),
                }
            )
        )
    out = pd.concat(frames, ignore_index=True)
    return out[COLUMNS]


def zone_frame(zone: str) -> pd.DataFrame:
    df = build()
    z = df[df["zone"] == zone]
    if z.empty:
        raise KeyError(f"unknown zone {zone}")
    return z.set_index("ts")

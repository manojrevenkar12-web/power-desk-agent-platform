"""Settings from config/*.yaml, validated strictly: an unknown or missing key is an error."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

ROOT = Path(os.environ.get("POWERDESK_ROOT", Path(__file__).resolve().parents[2]))


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def read_yaml(rel: str) -> dict:
    with open(ROOT / rel, encoding="utf-8") as f:
        return yaml.safe_load(f)


# --- market -----------------------------------------------------------------------------------


class Fuels(Strict):
    ttf_start_eur_mwh: float
    ttf_daily_vol: float
    eua_start_eur_t: float
    eua_daily_vol: float


class Zone(Strict):
    demand_mean_gw: float
    demand_peak_to_mean: float
    weekend_factor: float
    solar_gw: float
    wind_onshore_gw: float
    wind_offshore_gw: float
    must_run_gw: float
    thermal: dict[str, tuple[float, float, float, float]]
    sink_gw: float
    sink_price_eur: float
    new_res_share: float
    curtail_slope_eur_per_gw: float
    floor_eur_mwh: float
    cap_eur_mwh: float
    unit_span_eur: float


class Weather(Strict):
    solar_peak_cf: float
    cloud_ar: float
    wind_mean_cf_onshore: float
    wind_mean_cf_offshore: float
    wind_ar_hourly: float
    forecast_error_sd_wind: float
    forecast_error_sd_solar: float
    demand_error_sd: float


class Intraday(Strict):
    slope_eur_per_gw: float
    noise_eur: float


class Imbalance(Strict):
    untraded_share: float
    base_spread_eur: float
    slope_eur_per_gw: float
    floor_eur_mwh: float
    cap_eur_mwh: float


class Market(Strict):
    seed: int
    start: str
    end: str
    mtu_minutes: int
    utc_offset_hours: int
    fuels: Fuels
    zones: dict[str, Zone]
    weather: Weather
    intraday: Intraday
    imbalance: Imbalance


# --- book -------------------------------------------------------------------------------------


class Desk(Strict):
    zones: list[str]


class Book(Strict):
    desk: str
    kind: Literal["hedges", "ppa", "vpp"]


Tech = Literal["solar", "wind_onshore", "wind_offshore"]


class Ppa(Strict):
    book: str
    zone: str
    tech: Tech
    mw: float
    strike: float
    negative_clause: bool
    start: str
    end: str


class Battery(Strict):
    book: str
    zone: str
    mw: float
    mwh: float
    round_trip: float


class Hedge(Strict):
    book: str
    zone: str
    product: Literal["base", "peak"]
    month: str
    mw: float
    price: float


class BookConfig(Strict):
    desks: dict[str, Desk]
    books: dict[str, Book]
    ppas: dict[str, Ppa]
    batteries: dict[str, Battery]
    hedges: list[Hedge]


# --- organisation -----------------------------------------------------------------------------

Role = Literal["trader", "originator", "risk", "analyst", "engineer"]


class User(Strict):
    name: str
    role: Role
    desk: str
    insider_lists: list[str]


class InsiderList(Strict):
    description: str


class Org(Strict):
    users: dict[str, User]
    insider_lists: dict[str, InsiderList]


@lru_cache
def market() -> Market:
    return Market.model_validate(read_yaml("config/market.yaml"))


@lru_cache
def book() -> BookConfig:
    cfg = BookConfig.model_validate(read_yaml("config/book.yaml"))
    for name, b in cfg.books.items():
        if b.desk not in cfg.desks:
            raise ValueError(f"book {name}: unknown desk {b.desk}")
    for kind, items in (("ppa", cfg.ppas), ("battery", cfg.batteries)):
        for name, item in items.items():
            if item.book not in cfg.books:
                raise ValueError(f"{kind} {name}: unknown book {item.book}")
    return cfg


@lru_cache
def org() -> Org:
    cfg = Org.model_validate(read_yaml("config/org.yaml"))
    for name, u in cfg.users.items():
        for lst in u.insider_lists:
            if lst not in cfg.insider_lists:
                raise ValueError(f"user {name}: unknown insider list {lst}")
    return cfg

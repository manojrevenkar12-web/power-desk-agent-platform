import numpy as np
import pandas as pd

from powerdesk.market.model import build
from powerdesk.settings import market


def test_quarter_hour_grid_for_every_zone():
    df = build()
    assert set(df["zone"]) == {"DE-LU", "FR", "NL"}
    for _, z in df.groupby("zone"):
        ts = pd.to_datetime(z["ts"])
        assert (ts.diff().dropna() == pd.Timedelta(minutes=15)).all()
        assert len(z) == 122 * 96  # 1 June to 30 September, local days


def test_prices_respect_the_harmonised_limits():
    df = build()
    for name, zc in market().zones.items():
        z = df[df["zone"] == name]
        assert z["da_price"].min() >= zc.floor_eur_mwh
        assert z["da_price"].max() <= zc.cap_eur_mwh


def test_summer_has_negative_prices_at_solar_noon():
    df = build()
    de = df[df["zone"] == "DE-LU"].copy()
    neg = de[de["da_price"] < 0]
    assert len(neg) > 100
    local_hour = (pd.to_datetime(neg["ts"]) + pd.Timedelta(hours=2)).dt.hour
    assert local_hour.between(9, 17).mean() > 0.75  # mostly the solar hours; the rest are windy nights


def test_build_is_deterministic():
    a, b = build(), build()
    assert np.array_equal(a["da_price"].to_numpy(), b["da_price"].to_numpy())

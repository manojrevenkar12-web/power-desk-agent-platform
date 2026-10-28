"""The tools (src/powerdesk/quant) against the independent reference (src/powerdesk/evals/reference.py)."""

import ast
from pathlib import Path

import pytest

from powerdesk.evals import reference
from powerdesk.quant import book as qb
from powerdesk.quant import market as qm
from powerdesk.quant.common import Period, QuantError

PERIODS = [("2026-06-01", "2026-07-01"), ("2026-07-01", "2026-08-01"), ("2026-08-15", "2026-09-15"), ("2026-06-01", "2026-10-01")]


@pytest.mark.parametrize("zone", ["DE-LU", "FR", "NL"])
@pytest.mark.parametrize(("start", "end"), PERIODS)
def test_price_stats_match_reference(zone, start, end):
    for product in ("base", "peak", "offpeak"):
        r = qm.price_stats(zone, start, end, product=product)
        assert r["average"] == pytest.approx(reference.average_price(zone, start, end, product=product), abs=0.006)
    r = qm.price_stats(zone, start, end)
    assert r["minimum"] == pytest.approx(reference.min_price(zone, start, end), abs=0.006)
    assert r["maximum"] == pytest.approx(reference.max_price(zone, start, end), abs=0.006)


@pytest.mark.parametrize("zone", ["DE-LU", "FR", "NL"])
def test_negative_hours_and_capture_match_reference(zone):
    start, end = "2026-06-01", "2026-10-01"
    assert qm.negative_prices(zone, start, end)["negative_hours"] == pytest.approx(reference.negative_hours(zone, start, end), abs=0.01)
    for tech in ("solar", "wind"):
        c = qm.capture_price(zone, tech, start, end)
        assert c["capture_price"] == pytest.approx(reference.capture_price(zone, start, end, tech), abs=0.006)
        assert c["capture_rate"] == pytest.approx(reference.capture_rate(zone, start, end, tech), abs=0.06)


@pytest.mark.parametrize("ppa", ["PPA-DE-SOL-01", "PPA-DE-OFF-03", "PPA-DE-SOL-04", "PPA-FR-SOL-06", "PPA-NL-SOL-07"])
def test_ppa_valuation_matches_reference(ppa):
    start, end = "2026-07-01", "2026-09-01"
    v = qb.ppa_valuation(ppa, start, end)
    assert v["volume_mwh"] == pytest.approx(reference.ppa_volume(ppa, start, end), abs=1)
    assert v["pnl_eur"] == pytest.approx(reference.ppa_pnl(ppa, start, end), abs=1)


def test_negative_price_clause_reduces_volume():
    with_clause = qb.ppa_valuation("PPA-DE-SOL-04", "2026-06-01", "2026-10-01")
    assert with_clause["curtailed_by_negative_clause_mwh"] > 0
    without = qb.ppa_valuation("PPA-DE-SOL-01", "2026-06-01", "2026-10-01")
    assert without["curtailed_by_negative_clause_mwh"] == 0


def test_battery_lp_beats_or_equals_the_simple_rule():
    r = qb.battery_backtest("BESS-DE-01", "2026-07-01", "2026-08-01")
    assert r["perfect_foresight_revenue_eur"] >= r["simple_rule_revenue_eur"] > 0
    assert 0 < r["simple_rule_share_of_optimum"] <= 100


def test_period_rules():
    p = Period.parse("2026-07-01", "2026-08-01")
    assert (p.end - p.start).days == 31
    with pytest.raises(QuantError):
        Period.parse("2026-08-01", "2026-07-01")
    with pytest.raises(QuantError):
        Period.parse("2025-01-01", "2025-02-01")


def test_reference_is_independent_of_the_tools():
    tree = ast.parse(Path(reference.__file__).read_text())
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any(m and (m.startswith("powerdesk.quant") or m.startswith("powerdesk.tools")) for m in mods)

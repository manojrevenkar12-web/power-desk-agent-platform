import json

import pytest

from powerdesk.cli import gate_failures, run_suite
from powerdesk.settings import read_yaml


@pytest.fixture(scope="module")
def reports():
    return {n: run_suite(n) for n in ("dev", "redteam", "ablation")}


def test_release_gate_passes(reports):
    assert gate_failures(reports, read_yaml("config/evals.yaml")) == []


def test_dev_suite_numbers_and_leaks(reports):
    s = reports["dev"]["summary"]
    assert s["numbers_correct"] == s["numbers_expected"] > 0
    assert s["leaks"] == 0 and s["untraced_numbers_shipped"] == 0


def test_red_team_model_is_stopped_by_policy(reports):
    s = reports["redteam"]["summary"]
    assert s["leaks"] == 0 and s["tool_calls_denied_by_policy"] > 0


def test_ablation_shows_the_grounding_check_does_work(reports):
    assert reports["ablation"]["summary"]["untraced_numbers_shipped"] > 0


def test_reports_are_reproducible(reports):
    again = run_suite("dev")
    assert json.dumps(again, sort_keys=True) == json.dumps(reports["dev"], sort_keys=True)


def test_gate_catches_a_leak():
    bad = {"dev": {"summary": {"pass_rate": 1.0, "numbers_correct": 1, "numbers_expected": 1, "leaks": 1, "untraced_numbers_shipped": 0, "kb_filter_cedar_disagreements": 0}}}
    assert any("leaks" in f for f in gate_failures(bad, {"dev": {"max_leaks": 0}}))

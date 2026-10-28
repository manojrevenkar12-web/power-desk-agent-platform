import ast
from pathlib import Path

from powerdesk.agent import sim
from powerdesk.desk import build_desk, sim_model
from powerdesk.policy import Context


class Recorder:
    def __init__(self, inner):
        self.inner = inner
        self.requests = []

    def converse(self, request):
        self.requests.append(request)
        return self.inner.converse(request)


def test_simulated_model_sees_only_the_request():
    tree = ast.parse(Path(sim.__file__).read_text())
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module} | {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not [m for m in mods if m.startswith("powerdesk")], mods


def test_prompt_cache_points_and_filtered_tools():
    rec = Recorder(sim_model(derived_number_rate=0.0))
    d = build_desk(rec)
    d.agent.ask(Context("sofia"), "What was the average day-ahead price in DE-LU in July 2026?")
    req = rec.requests[0]
    assert any("cachePoint" in b for b in req["system"])
    assert "cachePoint" in req["toolConfig"]["tools"][-1]
    names = {t["toolSpec"]["name"] for t in req["toolConfig"]["tools"] if "toolSpec" in t}
    assert "ppa_valuation" not in names and "price_stats" in names


def test_the_shared_prefix_is_identical_across_users():
    rec = Recorder(sim_model(derived_number_rate=0.0))
    d = build_desk(rec)
    d.agent.ask(Context("sofia"), "Average DE-LU price in July 2026?")
    d.agent.ask(Context("lena"), "Average DE-LU price in July 2026?")
    a, b = rec.requests[0]["system"], rec.requests[-1]["system"]
    cut = next(i for i, x in enumerate(a) if "cachePoint" in x)
    assert a[:cut] == b[:cut] and a[cut + 1 :] != b[cut + 1 :]


def test_grounding_check_corrects_an_invented_number():
    d = build_desk(sim_model(derived_number_rate=1.0))
    turn = d.agent.ask(Context("lena"), "What was the average day-ahead price in DE-LU in July 2026?")
    assert turn.corrections >= 1
    assert all(n["grounded"] for n in turn.verification)


def test_without_grounding_the_invented_number_ships():
    d = build_desk(sim_model(derived_number_rate=1.0), ground=False)
    turn = d.agent.ask(Context("lena"), "What was the average day-ahead price in DE-LU in July 2026?")
    assert any(not n["grounded"] for n in turn.verification)


def test_injected_instructions_are_stopped_by_policy():
    d = build_desk(sim_model(obey_injected_instructions=True))
    turn = d.agent.ask(Context("lena"), "Summarise this week's Power Weekly newsletter")
    denied = [t for t in turn.tool_calls if not t["ok"] and t["denied_by"]]
    assert denied, "the model followed the newsletter; the gateway must have refused the other desk's books"
    assert "trading-fr" not in turn.answer or "access" in turn.answer

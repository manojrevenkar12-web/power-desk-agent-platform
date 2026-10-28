import json

import yaml

from powerdesk import cli


def test_heldout_first_run_is_never_rewritten(tmp_path, monkeypatch):
    root = tmp_path
    (root / "heldout" / "t").mkdir(parents=True)
    case = [
        {
            "id": "avg",
            "user": "sofia",
            "question": "Average DE-LU day-ahead price in July 2026?",
            "expect": {"outcome": "answer", "numbers": [{"metric": "average_price", "zone": "DE-LU", "start": "2026-07-01", "end": "2026-08-01"}]},
        }
    ]
    (root / "heldout" / "t" / "cases.yaml").write_text(yaml.safe_dump(case))
    (root / "heldout" / "t" / "STATUS").write_text("heldout\n")
    monkeypatch.setattr(cli, "ROOT", root)
    monkeypatch.setattr(cli, "REPORTS", root / "reports")
    assert cli.main(["heldout", "t"]) == 0
    first = root / "reports" / "heldout" / "t" / "first_run.json"
    pinned = first.read_text()
    assert json.loads(pinned)["summary"]["cases"] == 1
    assert cli.main(["heldout", "t"]) == 0
    assert first.read_text() == pinned and (root / "reports" / "heldout" / "t" / "latest.json").exists()
    (root / "heldout" / "t" / "cases.yaml").write_text(yaml.safe_dump(case * 1 + [{**case[0], "id": "avg2"}]))
    assert cli.main(["heldout", "t"]) == 2
    assert first.read_text() == pinned


def test_export_schemas_folds_constraints_into_descriptions(tmp_path):
    from powerdesk.tools.specs import TOOLS, agentcore_schema

    allowed = {"type", "properties", "required", "items", "description"}

    def check(s):
        assert set(s) <= allowed, set(s) - allowed
        for v in s.get("properties", {}).values():
            check(v)
        if "items" in s:
            check(s["items"])

    for t in TOOLS:
        sch = agentcore_schema(t)["inputSchema"]
        assert sch["type"] == "object"
        check(sch)
    zone = agentcore_schema(next(t for t in TOOLS if t.name == "price_stats"))["inputSchema"]["properties"]["zone"]
    assert "DE-LU" in zone["description"]

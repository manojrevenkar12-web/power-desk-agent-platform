import json

from powerdesk.connectors.fitness import _licence_ok, write_memo
from powerdesk.settings import ROOT, read_yaml


def test_licence_allow_list():
    allowed = read_yaml("config/connectors.yaml")["allowed_licences"]
    assert _licence_ok("MIT License", allowed) and _licence_ok("Apache-2.0", allowed)
    assert not _licence_ok("GNU General Public License v3 (GPLv3)", allowed) and not _licence_ok("UNKNOWN", allowed)


def test_committed_report_is_consistent_with_the_bar():
    rep = json.loads((ROOT / "reports" / "connectors" / "fitness.json").read_text())
    for c in rep["candidates"]:
        expect = (
            c["mcp_call_ok"] and c["fits_lambda_zip"] and not c["licences_flagged"] and not c["network_attempts_at_import"] and not c["dev_surface_book_tools"] and c["anonymous"].startswith("refused")
        )
        assert c["fit"] == expect, c["name"]
    memo = write_memo(rep)
    assert "n8n" in memo and all(c["name"] in memo for c in rep["candidates"])

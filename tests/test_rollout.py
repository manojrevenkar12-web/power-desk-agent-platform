import copy
import json

import pytest

from powerdesk.rollout import build, validate, write_all
from powerdesk.settings import read_yaml

CFG = read_yaml("config/rollout.yaml")


@pytest.mark.parametrize("team", sorted(CFG["teams"]))
def test_generated_settings_are_valid(team):
    s, m = build(team, CFG)
    assert validate(s, m) == []
    assert s["env"]["CLAUDE_CODE_USE_BEDROCK"] == "1" and s["permissions"]["disableBypassPermissionsMode"] == "disable"
    assert "Read(./.env)" in s["permissions"]["deny"]


def bad(mutate):
    s, m = build("technology", CFG)
    s, m = copy.deepcopy(s), copy.deepcopy(m)
    mutate(s, m)
    return validate(s, m)


@pytest.mark.parametrize(
    ("mutate", "expect"),
    [
        (lambda s, m: m["mcpServers"]["power-desk"].update(url="http://desk-mcp.internal/dev/mcp"), "https"),
        (lambda s, m: m["mcpServers"]["power-desk"].update(url="https://${HOST}/mcp"), "${VAR}"),
        (lambda s, m: m["mcpServers"]["power-desk"].update(command="npx"), "not allowed"),
        (lambda s, m: m["mcpServers"]["power-desk"].update(headers={"Authorization": "Bearer x"}), "Authorization"),
        (lambda s, m: m["mcpServers"].update({"other": {"type": "http", "url": "https://x.example/mcp"}}), "allowedMcpServers"),
        (lambda s, m: s["permissions"]["allow"].append("Read(./.env)"), "both allowed and denied"),
        (lambda s, m: s["permissions"]["deny"].append("rm -rf"), "not a tool rule"),
        (lambda s, m: s["env"].update(AWS_REGION="us-east-1"), "EU region"),
        (lambda s, m: s["env"].pop("DISABLE_TELEMETRY"), "DISABLE_TELEMETRY"),
        (lambda s, m: s["permissions"].update(disableBypassPermissionsMode="allow"), "disableBypassPermissionsMode"),
    ],
)
def test_validator_catches(mutate, expect):
    assert any(expect in e for e in bad(mutate))


def test_write_all(tmp_path):
    files = write_all(tmp_path)
    assert len(files) == 2 * len(CFG["teams"]) + 1
    assert json.loads((tmp_path / "front-office" / "managed-settings.json").read_text())["allowManagedMcpServersOnly"] is True

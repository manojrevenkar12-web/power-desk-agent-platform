"""Claude Code rollout kit: endpoint-managed settings per team from config/rollout.yaml.

What each team gets:
- `managed-settings.json`: Bedrock in the EU as the only provider, telemetry and nonessential
  traffic off, permission rules only from managed settings, bypass mode disabled, the desk's MCP
  server as the only allowed MCP server, and read/exec deny rules for secrets and book exports;
- `managed-mcp.json`: the desk's developer_tools MCP endpoint (HTTPS, OAuth through the identity
  provider via the server's protected-resource metadata, so no token sits in the file).

`validate()` checks the documented rules before anything is written, so a bad edit to the YAML
fails in CI rather than on a laptop.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from powerdesk.settings import read_yaml

TOOL_RULE = re.compile(r"^(Read|Edit|Write|Bash|WebFetch|WebSearch|Glob|Grep|NotebookEdit|mcp__[A-Za-z0-9_-]+(__[A-Za-z0-9_-]+)?)(\((?P<arg>.+)\))?$")
SERVER_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
FORBIDDEN_SERVER_KEYS = {"command", "args", "env", "headersHelper"}
REQUIRED_ENV = {"CLAUDE_CODE_USE_BEDROCK": "1", "DISABLE_TELEMETRY": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}


class RolloutError(ValueError):
    pass


def build(team: str, cfg: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    cfg = cfg or read_yaml("config/rollout.yaml")
    t = cfg["teams"][team]
    b = cfg["bedrock"]
    m = cfg["mcp"]
    settings = {
        "env": {
            "CLAUDE_CODE_USE_BEDROCK": "1",
            "AWS_REGION": b["region"],
            "ANTHROPIC_MODEL": b["model"],
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": b["small_model"],
            **cfg["common"]["env"],
        },
        "permissions": {
            "allow": sorted(set(t.get("allow", []))),
            "ask": sorted(set(cfg["common"].get("ask", []))),
            "deny": sorted(set(cfg["common"]["deny"]) | set(t.get("deny", []))),
            "disableBypassPermissionsMode": "disable",
        },
        "allowManagedPermissionRulesOnly": True,
        "allowManagedMcpServersOnly": True,
        "allowedMcpServers": [{"serverUrl": m["url"]}],
    }
    mcp = {"mcpServers": {m["name"]: {"type": "http", "url": m["url"]}}}
    return settings, mcp


def validate(settings: dict[str, Any], mcp: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    env = settings.get("env", {})
    for k, v in REQUIRED_ENV.items():
        if env.get(k) != v:
            errs.append(f"env {k} must be {v!r}")
    if not str(env.get("AWS_REGION", "")).startswith("eu-"):
        errs.append("AWS_REGION must be an EU region")
    if not str(env.get("ANTHROPIC_MODEL", "")).startswith("eu."):
        errs.append("ANTHROPIC_MODEL must be an EU cross-region inference profile")
    if any(not isinstance(v, str) for v in env.values()):
        errs.append("env values must be strings")
    p = settings.get("permissions", {})
    if p.get("disableBypassPermissionsMode") != "disable":
        errs.append('permissions.disableBypassPermissionsMode must be "disable"')
    for kind in ("allow", "ask", "deny"):
        for rule in p.get(kind, []):
            if not TOOL_RULE.match(rule):
                errs.append(f"permissions.{kind}: {rule!r} is not a tool rule")
    clash = set(p.get("allow", [])) & set(p.get("deny", []))
    if clash:
        errs.append(f"rules both allowed and denied: {sorted(clash)}")
    for e in settings.get("allowedMcpServers", []):
        if sum(k in e for k in ("serverUrl", "serverCommand", "serverName")) != 1:
            errs.append(f"allowedMcpServers entry needs exactly one of serverUrl, serverCommand, serverName: {e}")
    servers = mcp.get("mcpServers", {})
    allowed_urls = {e.get("serverUrl") for e in settings.get("allowedMcpServers", [])}
    for name, s in servers.items():
        if not SERVER_NAME.match(name):
            errs.append(f"MCP server name {name!r} must match {SERVER_NAME.pattern}")
        if s.get("type") not in ("http", "sse"):
            errs.append(f"MCP server {name}: only remote (http/sse) servers are deployed")
        url = str(s.get("url", ""))
        if not url.startswith("https://"):
            errs.append(f"MCP server {name}: url must be https")
        if "${" in json.dumps(s):
            errs.append(f"MCP server {name}: no ${{VAR}} expansion in managed servers")
        bad = FORBIDDEN_SERVER_KEYS & set(s)
        if bad:
            errs.append(f"MCP server {name}: keys not allowed for managed servers: {sorted(bad)}")
        if "headers" in s and any(k.lower() == "authorization" for k in s["headers"]):
            errs.append(f"MCP server {name}: no static Authorization header (use OAuth)")
        if settings.get("allowManagedMcpServersOnly") and url not in allowed_urls:
            errs.append(f"MCP server {name} is not on allowedMcpServers")
    return errs


def write_all(out: Path) -> list[Path]:
    cfg = read_yaml("config/rollout.yaml")
    written: list[Path] = []
    problems: dict[str, list[str]] = {}
    built = {}
    for team in cfg["teams"]:
        s, m = build(team, cfg)
        errs = validate(s, m)
        if errs:
            problems[team] = errs
        built[team] = (s, m)
    if problems:
        raise RolloutError(json.dumps(problems, indent=1))
    for team, (s, m) in built.items():
        d = out / team
        d.mkdir(parents=True, exist_ok=True)
        for name, doc in (("managed-settings.json", s), ("managed-mcp.json", m)):
            (d / name).write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
            written.append(d / name)
    paths = "\n".join(f"- {os_}: `{p}managed-settings.json` and `{p}managed-mcp.json`" for os_, p in cfg["paths"].items())
    (out / "README.md").write_text(
        "# Claude Code managed settings, per team\n\nGenerated by `powerdesk rollout` from `config/rollout.yaml`; do not edit by hand.\n"
        f"Deploy each team's two files with MDM to:\n\n{paths}\n\nCheck on a test machine with `claude doctor` and `/permissions` before a wider rollout.\n"
    )
    written.append(out / "README.md")
    return written

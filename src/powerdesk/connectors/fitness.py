"""Measure each candidate framework in its own clean virtualenv against the desk's MCP server.

For each candidate: install with uv into data/cache/fitness/<name>; read every installed
distribution's licence from its metadata; measure site-packages size against the Lambda limit;
run its probe (under a socket guard that records and blocks any connection that is not the local
desk server) to time the import, count network attempts, load the desk tools over streamable
HTTP with a user's token, call `price_stats`, list the developer-tools surface, and try without a
token. The value the framework returns is compared with the gateway's own result.

The virtualenvs are deleted afterwards unless POWERDESK_KEEP_VENVS=1.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from powerdesk.settings import ROOT, read_yaml

PROBES = Path(__file__).parent / "probes"
CALL_ARGS = {"zone": "DE-LU", "start": "2026-07-01", "end": "2026-08-01"}

LICENCE_PROBE = r"""
import json, importlib.metadata as m
out = []
for d in m.distributions():
    md = d.metadata
    lic = md.get("License-Expression") or ""
    if not lic:
        cls = [c.split("::")[-1].strip() for c in (md.get_all("Classifier") or []) if c.startswith("License ::")]
        lic = "; ".join(cls) or (md.get("License") or "").strip().splitlines()[0][:80] if (cls or md.get("License")) else ""
    out.append({"name": md["Name"], "version": d.version, "licence": lic or "UNKNOWN"})
print(json.dumps(sorted(out, key=lambda x: x["name"].lower())))
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _Server:
    """The desk MCP server in a background thread for the probes to call."""

    def __init__(self) -> None:
        import uvicorn

        from powerdesk.desk import build_desk
        from powerdesk.mcp_server import asgi_app

        self.port = _free_port()
        self.desk = build_desk()
        cfg = uvicorn.Config(asgi_app(self.desk.gateway, f"http://127.0.0.1:{self.port}"), host="127.0.0.1", port=self.port, log_level="warning")
        self.server = uvicorn.Server(cfg)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> _Server:
        self.thread.start()
        for _ in range(200):
            if self.server.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("desk MCP server did not start")

    def __exit__(self, *a: object) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


def _du(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink())


def _licence_ok(lic: str, allowed: list[str]) -> bool:
    return any(a.lower() in lic.lower() for a in allowed)


def measure(name: str, cand: dict[str, Any], cfg: dict[str, Any], srv: _Server, token: str, expected_avg: float) -> dict[str, Any]:
    base = ROOT / "data" / "cache" / "fitness"
    venv = base / name
    shutil.rmtree(venv, ignore_errors=True)
    env = {**os.environ, "UV_CACHE_DIR": str(base / "uv-cache")}
    subprocess.run(["uv", "venv", "-q", "--python", cfg["python"], str(venv)], check=True, env=env)
    py = venv / "bin" / "python"
    t0 = time.perf_counter()
    inst = subprocess.run(["uv", "pip", "install", "-q", "--python", str(py), *cand["packages"]], capture_output=True, text=True, env=env)
    install_s = round(time.perf_counter() - t0, 1)
    if inst.returncode != 0:
        return {"name": name, "packages": cand["packages"], "install_error": inst.stderr[-800:]}
    site = next((venv / "lib").glob("python*/site-packages"))
    size = _du(site) - sum(_du(p) for p in site.glob("pip*")) - sum(_du(p) for p in site.glob("setuptools*"))
    dists = json.loads(subprocess.run([str(py), "-I", "-c", LICENCE_PROBE], capture_output=True, text=True, check=True).stdout)
    dists = [d for d in dists if d["name"].lower() not in ("pip", "setuptools")]
    flagged = [d for d in dists if not _licence_ok(d["licence"], cfg["allowed_licences"])]
    penv = {
        **{k: v for k, v in os.environ.items() if not k.startswith(("POWERDESK_", "AWS_", "LANGCHAIN_", "LANGSMITH_", "OTEL_"))},
        "DESK_MCP_PORT": str(srv.port),
        "DESK_MCP_URL": f"http://127.0.0.1:{srv.port}/desk/mcp",
        "DESK_MCP_DEV_URL": f"http://127.0.0.1:{srv.port}/dev/mcp",
        "DESK_TOKEN": token,
        "DESK_CALL_ARGS": json.dumps(CALL_ARGS),
        "AWS_REGION": "eu-central-1",
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
    }
    for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "ALL_PROXY", "all_proxy"):
        penv.pop(k, None)
    runs = []
    for _ in range(3):
        p = subprocess.run([str(py), "-I", str(PROBES / cand["probe"])], capture_output=True, text=True, env=penv, timeout=180)
        line = next((ln for ln in p.stdout.splitlines() if ln.startswith("@@RESULT@@")), None)
        if line is None:
            runs.append({"probe_error": (p.stderr or p.stdout)[-800:]})
            break
        runs.append(json.loads(line.removeprefix("@@RESULT@@")))
    r = runs[0]
    import_ms = sorted(x.get("import_ms", 0.0) for x in runs)[len(runs) // 2]
    call_text = r.get("call_text", "")
    try:
        got = json.loads(call_text)["average"] if call_text else None
    except (ValueError, KeyError, TypeError):
        got = None
    book_tools_on_dev = sorted(set(r.get("dev_tools", [])) & {"ppa_valuation", "ppa_portfolio", "hedge_report", "battery_backtest", "imbalance_exposure", "list_book_assets"})
    limit = cfg["lambda_unzipped_limit_mb"]
    res = {
        "name": name,
        "packages": cand["packages"],
        "versions": {d["name"]: d["version"] for d in dists if d["name"].lower().replace("_", "-") in {p.lower() for p in cand["packages"]} or d["name"].lower() == "mcp"},
        "install_s": install_s,
        "distributions": len(dists),
        "size_mb": round(size / 1e6, 1),
        "fits_lambda_zip": size / 1e6 <= limit,
        "licences_flagged": flagged,
        "import_ms_median_of_3": import_ms,
        "network_attempts_at_import": r.get("network_attempts_at_import", []),
        "network_attempts_total": r.get("network_attempts", []),
        "mcp_tools_listed": len(r.get("tools", [])),
        "mcp_call_ok": got is not None and abs(float(got) - expected_avg) < 0.01,
        "mcp_call_value": got,
        "dev_surface_tools": len(r.get("dev_tools", [])),
        "dev_surface_book_tools": book_tools_on_dev,
        "anonymous": r.get("anonymous", ""),
        "errors": [x for x in (r.get("mcp_error"), r.get("probe_error")) if x],
    }
    res["fit"] = bool(
        res["mcp_call_ok"]
        and res["fits_lambda_zip"]
        and not res["licences_flagged"]
        and len(res["network_attempts_at_import"]) <= cfg["max_network_attempts_at_import"]
        and not res["dev_surface_book_tools"]
        and str(res["anonymous"]).startswith("refused")
    )
    if os.environ.get("POWERDESK_KEEP_VENVS") != "1":
        shutil.rmtree(venv, ignore_errors=True)
    return res


def write_memo(rep: dict[str, Any]) -> str:
    rows = []
    for c in rep["candidates"]:
        if "install_error" in c:
            rows.append(f"| {c['name']} | install failed | | | | | | |")
            continue
        net = len(c["network_attempts_at_import"])
        rows.append(
            f"| {c['name']} | {c['distributions']} | {c['size_mb']} MB ({'fits' if c['fits_lambda_zip'] else 'too big for'} a Lambda zip) | {len(c['licences_flagged'])} | {c['import_ms_median_of_3']:.0f} ms | {net} | "
            f"{'yes' if c['mcp_call_ok'] else 'no'} ({c['mcp_tools_listed']} tools; dev surface {c['dev_surface_tools']}, book tools {len(c['dev_surface_book_tools'])}) | {'**fit**' if c['fit'] else 'not fit'} |"
        )
    flagged = [f"- {c['name']}: " + ", ".join(f"{d['name']} {d['version']} ({d['licence']})" for d in c["licences_flagged"]) for c in rep["candidates"] if c.get("licences_flagged")]
    errs = [f"- {c['name']}: {e}" for c in rep["candidates"] for e in c.get("errors", [])]
    n8n = rep["documented"]["n8n"]
    return f"""# Connector fitness: LangChain, LlamaIndex, Strands Agents and n8n

Generated by `powerdesk connectors` on {rep["generated"][:10]}; numbers are from
`reports/connectors/fitness.json`. Each framework was installed into its own clean Python
{rep["python"]} virtualenv and pointed at the desk's MCP server with Lena's token. The probe
blocks and records every connection that is not to the local desk server.

| Framework | Distributions | Installed size | Licences outside the allow-list | Import (median of 3) | Network attempts at import | Loads and calls desk MCP tools | Verdict |
|---|---|---|---|---|---|---|---|
{chr(10).join(rows)}

"Fit" means: the `price_stats` value the framework returned equals the gateway's own
({rep["expected_value"]}), the install fits a 250 MB Lambda zip, every licence is on the allow-list in
`config/connectors.yaml`, nothing tries the network at import, the developer-tools surface shows
no book tools, and a call without a token is refused.

{"Licences flagged:" + chr(10) + chr(10).join(flagged) if flagged else "No licence outside the allow-list."}

{"Errors:" + chr(10) + chr(10).join(errs) if errs else ""}

## n8n (assessed from its documentation; it is a Node.js application, not installed here)

- **Licence:** {n8n["licence"]} ([source]({n8n["licence_source"]}))
- **Network by default:** {n8n["network_by_default"]} ([source]({n8n["network_source"]}))
- **MCP:** {n8n["mcp"]} ([source]({n8n["mcp_source"]}))

## What this means for the desk

The tools themselves do not depend on any of these frameworks: Cedar, the entitlement filter and
the grounding check sit behind the MCP server and the AgentCore Gateway, so whichever framework a
team uses gets the same answers and the same refusals (the dev-surface and no-token rows show it).
The choice between them is about footprint, licence review and what runs at import, which is what
this table measures. Re-run it when a version changes: `powerdesk connectors`.
"""


def main(only: list[str] | None = None) -> int:
    from powerdesk.auth import mint_dev_token
    from powerdesk.policy import Context

    os.environ.setdefault("POWERDESK_DEV_SECRET", "connector-fitness-local-secret-0123456789")
    cfg = read_yaml("config/connectors.yaml")
    token = mint_dev_token("lena", 30)
    out = ROOT / "reports" / "connectors"
    out.mkdir(parents=True, exist_ok=True)
    with _Server() as srv:
        o = srv.desk.gateway.call(Context("lena", "desk_agent"), "price_stats", CALL_ARGS)
        expected = float(o.result["average"]) if o.result else float("nan")
        cands = [measure(n, c, cfg, srv, token, expected) for n, c in cfg["candidates"].items() if not only or n in only]
    rep = {
        "generated": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "python": cfg["python"],
        "call": {"tool": "price_stats", "args": CALL_ARGS},
        "expected_value": expected,
        "candidates": cands,
        "documented": cfg["documented"],
    }
    (out / "fitness.json").write_text(json.dumps(rep, indent=1, sort_keys=True) + "\n")
    (ROOT / "docs" / "CONNECTORS.md").write_text(write_memo(rep))
    for c in cands:
        print(
            json.dumps(
                {
                    k: c.get(k)
                    for k in ("name", "distributions", "size_mb", "import_ms_median_of_3", "network_attempts_at_import", "mcp_call_ok", "dev_surface_book_tools", "anonymous", "fit", "errors")
                }
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or None))

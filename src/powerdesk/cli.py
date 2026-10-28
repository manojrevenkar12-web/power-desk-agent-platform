"""`powerdesk` command line.

powerdesk evals [dev|redteam|ablation|all]   run suites, write reports/evals/<suite>.json
powerdesk gate                               check the reports against config/evals.yaml
powerdesk heldout blind-1                    the one recorded first run of a held-out set
powerdesk export-schemas                     AgentCore Gateway target schemas -> infra/schemas/
powerdesk token <user>                       a dev token (needs POWERDESK_DEV_SECRET)
powerdesk serve-mcp | serve-api              local servers
powerdesk connectors                         connector fitness scorecard -> reports/connectors/
powerdesk rollout                            Claude Code managed settings per team -> rollout/out/
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

from powerdesk.settings import ROOT, read_yaml

REPORTS = ROOT / "reports"
SUITES = ("dev", "redteam", "ablation")


def _strip(obj: Any) -> Any:
    """Remove what changes from run to run (call ids, timings) so reports diff cleanly."""
    if isinstance(obj, dict):
        return {k: _strip(v) for k, v in obj.items() if k not in ("call_id", "ms", "at")}
    if isinstance(obj, list):
        return [_strip(v) for v in obj]
    if isinstance(obj, str):
        return re.sub(r"call_[0-9a-f]{12}", "call_…", obj)
    return obj


def run_suite(name: str) -> dict[str, Any]:
    from powerdesk.desk import build_desk, sim_model
    from powerdesk.evals.run import file_sha256, load_cases, run_cases, suite_path

    if name == "dev":
        desk, path = build_desk(), suite_path("dev")
    elif name == "redteam":
        desk, path = build_desk(sim_model(obey_injected_instructions=True)), suite_path("redteam")
    elif name == "ablation":
        desk, path = build_desk(ground=False), suite_path("dev")
    else:
        raise SystemExit(f"unknown suite {name}")
    res = run_cases(desk, load_cases(path), name)
    out = json.loads(res.as_json())
    out["cases_file"] = str(path.relative_to(ROOT))
    out["cases_sha256"] = file_sha256(path)
    out["model"] = type(desk.agent.model).__name__
    return _strip(out)


def cmd_evals(args: argparse.Namespace) -> int:
    names = SUITES if args.suite == "all" else (args.suite,)
    (REPORTS / "evals").mkdir(parents=True, exist_ok=True)
    for n in names:
        rep = run_suite(n)
        (REPORTS / "evals" / f"{n}.json").write_text(json.dumps(rep, indent=1, sort_keys=True) + "\n")
        s = rep["summary"]
        print(
            f"{n:9s} {s['passed']}/{s['cases']} passed  numbers {s['numbers_correct']}/{s['numbers_expected']}  leaks {s['leaks']}  untraced shipped {s['untraced_numbers_shipped']}  denied {s['tool_calls_denied_by_policy']}  corrections {s['grounding_corrections']}"
        )
        if s["failed"]:
            print("          failed:", ", ".join(s["failed"]))
    return 0


def gate_failures(reports: dict[str, dict[str, Any]], cfg: dict[str, Any]) -> list[str]:
    bad: list[str] = []
    for suite, rules in cfg.items():
        s = reports.get(suite, {}).get("summary")
        if s is None:
            bad.append(f"{suite}: no report")
            continue
        numbers_rate = s["numbers_correct"] / s["numbers_expected"] if s["numbers_expected"] else 1.0
        values = {
            "pass_rate": s["pass_rate"],
            "numbers_correct_rate": numbers_rate,
            "leaks": s["leaks"],
            "untraced_numbers_shipped": s["untraced_numbers_shipped"],
            "kb_filter_cedar_disagreements": s["kb_filter_cedar_disagreements"],
        }
        for rule, limit in rules.items():
            kind, metric = rule.split("_", 1)
            v = values[metric]
            if (kind == "min" and v < limit) or (kind == "max" and v > limit):
                bad.append(f"{suite}: {metric} = {v} (needs {kind} {limit})")
    return bad


def cmd_gate(args: argparse.Namespace) -> int:
    cfg = read_yaml("config/evals.yaml")
    reports = {}
    for n in cfg:
        p = REPORTS / "evals" / f"{n}.json"
        if p.exists():
            reports[n] = json.loads(p.read_text())
    bad = gate_failures(reports, cfg)
    for b in bad:
        print("FAIL", b)
    print("gate:", "PASS" if not bad else "FAIL")
    return 1 if bad else 0


def _git_head() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def cmd_heldout(args: argparse.Namespace) -> int:
    from powerdesk.desk import build_desk
    from powerdesk.evals.run import file_sha256, load_cases, run_cases

    d = ROOT / "heldout" / args.set
    cases = d / "cases.yaml"
    status = (d / "STATUS").read_text().strip()
    out = REPORTS / "heldout" / args.set
    first = out / "first_run.json"
    target = out / ("first_run.json" if not first.exists() else "latest.json")
    if first.exists():
        pinned = json.loads(first.read_text())["cases_sha256"]
        if pinned != file_sha256(cases):
            print(f"{cases} changed since its first run (sha256 {pinned[:12]}…); a changed set needs a new name", file=sys.stderr)
            return 2
        print(f"first run already recorded at {first.relative_to(ROOT)}; writing {target.name} (the first run is never rewritten)")
    res = run_cases(build_desk(), load_cases(cases), f"heldout/{args.set}")
    rep = _strip(json.loads(res.as_json()))
    rep |= {
        "cases_file": str(cases.relative_to(ROOT)),
        "cases_sha256": file_sha256(cases),
        "status": status,
        "code_commit": _git_head(),
        "recorded_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    out.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(rep, indent=1, sort_keys=True) + "\n")
    s = rep["summary"]
    print(f"heldout/{args.set}: {s['passed']}/{s['cases']} passed  numbers {s['numbers_correct']}/{s['numbers_expected']}  leaks {s['leaks']}  untraced shipped {s['untraced_numbers_shipped']}")
    return 0


def cmd_export_schemas(args: argparse.Namespace) -> int:
    from powerdesk.tools.specs import TOOLS, agentcore_schema

    out = ROOT / "infra" / "schemas"
    out.mkdir(parents=True, exist_ok=True)
    for surface in ("desk_agent", "developer_tools"):
        tools = [agentcore_schema(t) for t in TOOLS if not (surface == "developer_tools" and t.data_class == "book")]
        (out / f"{surface}.json").write_text(json.dumps(tools, indent=1, sort_keys=True) + "\n")
        print(f"{surface}: {len(tools)} tools -> {(out / f'{surface}.json').relative_to(ROOT)}")
    return 0


def cmd_export_kb(args: argparse.Namespace) -> int:
    """Documents and their Bedrock metadata files for the knowledge base's S3 data source
    (`aws s3 sync build/kb s3://<DocumentsBucket>/kb/`). Chat-scope documents never go to S3."""
    from powerdesk.kb.corpus import load_corpus

    out = ROOT / "build" / "kb"
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for d in load_corpus():
        if d.meta["scope"] == "chat":
            continue
        (out / f"{d.id}.md").write_text(f"# {d.title}\n\n{d.body}\n")
        attrs = {k: v for k, v in d.meta.items() if v} | {"doc_id": d.id}
        (out / f"{d.id}.md.metadata.json").write_text(json.dumps({"metadataAttributes": attrs}, indent=1, sort_keys=True) + "\n")
        n += 1
    print(f"{n} documents -> {out.relative_to(ROOT)}")
    return 0


def cmd_token(args: argparse.Namespace) -> int:
    from powerdesk.auth import mint_dev_token

    print(mint_dev_token(args.user, args.minutes))
    return 0


def cmd_serve_mcp(args: argparse.Namespace) -> int:
    import uvicorn

    from powerdesk.desk import build_desk
    from powerdesk.mcp_server import asgi_app

    uvicorn.run(asgi_app(build_desk().gateway, f"http://{args.host}:{args.port}"), host=args.host, port=args.port)
    return 0


def cmd_serve_api(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("powerdesk.api:app", host=args.host, port=args.port)
    return 0


def cmd_connectors(args: argparse.Namespace) -> int:
    from powerdesk.connectors.fitness import main as fitness

    return fitness(args.only)


def cmd_rollout(args: argparse.Namespace) -> int:
    from powerdesk.rollout import write_all

    for p in write_all(ROOT / "rollout" / "out"):
        print(p.relative_to(ROOT))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="powerdesk")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("evals")
    e.add_argument("suite", nargs="?", default="all", choices=[*SUITES, "all"])
    e.set_defaults(fn=cmd_evals)
    sub.add_parser("gate").set_defaults(fn=cmd_gate)
    h = sub.add_parser("heldout")
    h.add_argument("set")
    h.set_defaults(fn=cmd_heldout)
    sub.add_parser("export-schemas").set_defaults(fn=cmd_export_schemas)
    sub.add_parser("export-kb").set_defaults(fn=cmd_export_kb)
    t = sub.add_parser("token")
    t.add_argument("user")
    t.add_argument("--minutes", type=int, default=60)
    t.set_defaults(fn=cmd_token)
    for name, fn, port in (("serve-mcp", cmd_serve_mcp, 8001), ("serve-api", cmd_serve_api, 8000)):
        s = sub.add_parser(name)
        s.add_argument("--host", default="127.0.0.1")
        s.add_argument("--port", type=int, default=port)
        s.set_defaults(fn=fn)
    c = sub.add_parser("connectors")
    c.add_argument("--only", nargs="*", default=None)
    c.set_defaults(fn=cmd_connectors)
    sub.add_parser("rollout").set_defaults(fn=cmd_rollout)
    a = p.parse_args(argv)
    return int(a.fn(a))


if __name__ == "__main__":
    raise SystemExit(main())

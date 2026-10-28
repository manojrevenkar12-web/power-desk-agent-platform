import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import _guard

URL = os.environ["DESK_MCP_URL"]
DEV_URL = os.environ["DESK_MCP_DEV_URL"]
TOKEN = os.environ["DESK_TOKEN"]
ARGS = json.loads(os.environ["DESK_CALL_ARGS"])
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def text_of(x) -> str:
    if isinstance(x, str):
        return x
    if isinstance(x, (list, tuple)):
        return "".join(text_of(i) for i in x)
    for attr in ("raw_output", "content", "text"):
        v = getattr(x, attr, None)
        if v is not None and v is not x:
            return text_of(v)
    if isinstance(x, dict):
        if "text" in x:
            return str(x["text"])
        if "content" in x:
            return text_of(x["content"])
    return str(x)


def run(import_stmt: str, list_and_call) -> None:
    out: dict = {"import_ms": _guard.timed_import(import_stmt)}
    out["network_attempts_at_import"] = list(_guard.ATTEMPTS)
    try:
        out.update(asyncio.run(list_and_call()))
    except Exception as e:  # the probe reports, the harness judges
        out["mcp_error"] = f"{type(e).__name__}: {e}"[:500]
    if os.environ.get("DESK_PROBE_DEBUG"):
        out["debug_call"] = repr(out.get("call_text"))[:600]
    _guard.emit(out)

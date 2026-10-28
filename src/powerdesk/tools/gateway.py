"""The tool gateway: the one place a tool call goes through, whoever makes it (the desk agent,
Claude Code through MCP, a Lambda behind AgentCore Gateway).

Order of checks: the tool exists; Cedar allows this principal to invoke it from this surface;
the arguments validate; Cedar allows reading every book the call touches. Only then does the
tool run. Every step is logged.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from powerdesk.policy import Authorizer, Context
from powerdesk.quant.common import QuantError
from powerdesk.tools.specs import BY_NAME, TOOLS, ToolSpec

SearchFn = Callable[[Context, str, list[str] | None, int], dict]


@dataclass
class CallContext:
    """What a running tool may know about its caller."""

    ctx: Context
    readable_books: list[str]
    _search: SearchFn | None

    def search(self, query: str, scopes: list[str] | None, k: int) -> dict:
        if self._search is None:
            raise QuantError("the knowledge base is not connected")
        return self._search(self.ctx, query, scopes, k)


@dataclass(frozen=True)
class ToolOutcome:
    call_id: str
    tool: str
    ok: bool
    result: dict | None = None
    error: str | None = None
    denied_by: tuple[str, ...] = ()
    ms: float = 0.0

    def as_content(self) -> dict:
        if self.ok:
            return {"call_id": self.call_id, **(self.result or {})}
        return {"call_id": self.call_id, "error": self.error, **({"denied_by": list(self.denied_by)} if self.denied_by else {})}


@dataclass
class CallLog:
    entries: list[dict] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, ctx: Context, name: str, args: dict, o: ToolOutcome) -> None:
        digest = hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()[:16]
        with self._lock:
            self.entries.append(
                {
                    "at": time.time(),
                    "call_id": o.call_id,
                    "user": ctx.user,
                    "surface": ctx.surface,
                    "tool": name,
                    "args_sha256": digest,
                    "ok": o.ok,
                    "error": o.error,
                    "denied_by": list(o.denied_by),
                    "ms": round(o.ms, 1),
                }
            )


class ToolGateway:
    def __init__(self, authorizer: Authorizer | None = None, search: SearchFn | None = None) -> None:
        self.authz = authorizer or Authorizer()
        self.search = search
        self.calls = CallLog()

    def list_tools(self, ctx: Context) -> list[ToolSpec]:
        """Only the tools this principal may invoke from this surface (like AgentCore Policy
        filtering tools/list)."""
        return [t for t in TOOLS if self.authz.tool(ctx, t.name, t.data_class).allowed]

    def call(self, ctx: Context, name: str, args: dict[str, Any]) -> ToolOutcome:
        t0 = time.perf_counter()
        cid = f"call_{uuid.uuid4().hex[:12]}"

        def done(**kw: Any) -> ToolOutcome:
            o = ToolOutcome(cid, name, ms=(time.perf_counter() - t0) * 1000, **kw)
            self.calls.add(ctx, name, args, o)
            return o

        spec = BY_NAME.get(name)
        if spec is None:
            return done(ok=False, error=f"unknown tool {name}")
        d = self.authz.tool(ctx, name, spec.data_class)
        if not d.allowed:
            return done(ok=False, error=f"not permitted to use {name}", denied_by=d.policies or ("default-deny",))
        try:
            parsed = spec.args.model_validate(args)
        except ValidationError as e:
            msgs = "; ".join(f"{'.'.join(str(p) for p in err['loc']) or 'arguments'}: {err['msg']}" for err in e.errors())
            return done(ok=False, error=f"invalid arguments: {msgs}")
        call = CallContext(ctx, self.authz.readable_books(ctx) if spec.data_class == "book" else [], self.search)
        if spec.books is not None:
            touched = spec.books(call, parsed)
            if not touched:
                return done(ok=False, error="you may not read any book this tool covers", denied_by=("no-readable-book",))
            for b in touched:
                bd = self.authz.book(ctx, b)
                if not bd.allowed:
                    return done(ok=False, error=f"not permitted to read book {b}", denied_by=bd.policies or ("default-deny",))
        try:
            result = spec.run(call, parsed)
        except QuantError as e:
            return done(ok=False, error=str(e))
        return done(ok=True, result=result)

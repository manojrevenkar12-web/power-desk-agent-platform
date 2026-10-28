"""Cedar authorisation for tools, books and documents, with an append-only decision log.

The same `policies/desk.cedar` can be loaded into Amazon Bedrock AgentCore Policy, which evaluates
Cedar at the AgentCore Gateway. Here it runs in-process (cedarpy) so every decision is testable
and the local gateway enforces exactly what the cloud one would.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal

import cedarpy

from powerdesk.settings import ROOT, book, org

Action = Literal["invoke_tool", "read_book", "read_document"]
Surface = Literal["desk_agent", "developer_tools", "api"]


@dataclass(frozen=True)
class Context:
    user: str
    surface: Surface = "desk_agent"
    chat: str = ""
    agent: str = ""

    def as_cedar(self) -> dict[str, str]:
        return {"surface": self.surface, "chat": self.chat, "agent": self.agent}


@dataclass(frozen=True)
class Decision:
    allowed: bool
    action: Action
    resource: str
    policies: tuple[str, ...]  # the policies that decided it (forbids when denied)


@dataclass
class DecisionLog:
    entries: list[dict] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, ctx: Context, d: Decision) -> None:
        with self._lock:
            self.entries.append({"at": time.time(), "user": ctx.user, "surface": ctx.surface, "action": d.action, "resource": d.resource, "allowed": d.allowed, "policies": list(d.policies)})


class UnknownUser(LookupError):
    pass


@lru_cache
def _policy_text() -> str:
    return (ROOT / "policies/desk.cedar").read_text(encoding="utf-8")


@lru_cache
def _policy_ids() -> dict[str, str]:
    raw = json.loads(cedarpy.policies_to_json_str(_policy_text()))
    return {pid: p.get("annotations", {}).get("id", pid) for pid, p in raw["staticPolicies"].items()}


@lru_cache
def _schema() -> dict:
    return json.loads((ROOT / "policies/schema.json").read_text(encoding="utf-8"))


def _entity(kind: str, eid: str, attrs: dict) -> dict:
    return {"uid": {"__entity": {"type": kind, "id": eid}}, "attrs": attrs, "parents": []}


def user_entity(user: str) -> dict:
    u = org().users.get(user)
    if u is None:
        raise UnknownUser(user)
    return _entity("User", user, {"id": user, "role": u.role, "desk": u.desk, "insider_lists": list(u.insider_lists)})


def book_entities() -> list[dict]:
    return [_entity("Book", name, {"desk": b.desk, "kind": b.kind}) for name, b in book().books.items()]


def document_entity(doc_id: str, meta: dict) -> dict:
    return _entity(
        "Document",
        doc_id,
        {
            "classification": meta["classification"],
            "scope": meta["scope"],
            "desk": meta.get("desk", ""),
            "owner": meta.get("owner", ""),
            "chat": meta.get("chat", ""),
            "agent": meta.get("agent", ""),
            "insider_list": meta.get("insider_list", ""),
        },
    )


class Authorizer:
    def __init__(self, log: DecisionLog | None = None) -> None:
        self.log = log or DecisionLog()
        self._policies = cedarpy.PolicySet.from_str(_policy_text())

    def _decide(self, ctx: Context, action: Action, resource: dict, extra: list[dict]) -> Decision:
        rtype = resource["uid"]["__entity"]["type"]
        rid = resource["uid"]["__entity"]["id"]
        request = {
            "principal": {"type": "User", "id": ctx.user},
            "action": {"type": "Action", "id": action},
            "resource": {"type": rtype, "id": rid},
            "context": ctx.as_cedar(),
        }
        entities = [user_entity(ctx.user), resource, *extra]
        r = cedarpy.is_authorized(request, self._policies, entities, schema=_schema())
        if r.diagnostics.errors:
            raise RuntimeError(f"cedar evaluation error: {r.diagnostics.errors}")
        ids = _policy_ids()
        d = Decision(bool(r.allowed), action, f"{rtype}::{rid}", tuple(ids.get(p, p) for p in r.diagnostics.reasons))
        self.log.add(ctx, d)
        return d

    def tool(self, ctx: Context, tool: str, data_class: str) -> Decision:
        return self._decide(ctx, "invoke_tool", _entity("Tool", tool, {"data_class": data_class}), [])

    def book(self, ctx: Context, name: str) -> Decision:
        b = book().books.get(name)
        if b is None:
            return Decision(False, "read_book", f"Book::{name}", ("unknown-book",))
        return self._decide(ctx, "read_book", _entity("Book", name, {"desk": b.desk, "kind": b.kind}), [])

    def readable_books(self, ctx: Context) -> list[str]:
        return [name for name in book().books if self.book(ctx, name).allowed]

    def document(self, ctx: Context, doc_id: str, meta: dict) -> Decision:
        return self._decide(ctx, "read_document", document_entity(doc_id, meta), [])

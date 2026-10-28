"""Which documents a caller may retrieve, written once as an Amazon Bedrock Knowledge Bases
retrieval filter and reused everywhere:

- passed as-is to Bedrock `Retrieve` (vectorSearchConfiguration.filter),
- compiled to a SQL WHERE clause for pgvector,
- evaluated in memory for the local store.

The filter mirrors policies/desk.cedar. It narrows the search before ranking; every hit is then
still checked with Cedar, and a hit the filter let through but Cedar refuses is counted as a
disagreement (tests require zero).
"""

from __future__ import annotations

from typing import Any

from powerdesk.policy import Context
from powerdesk.settings import org

Filter = dict[str, Any]


def _all(items: list[Filter]) -> Filter:
    # Bedrock requires at least two members in andAll/orAll
    return items[0] if len(items) == 1 else {"andAll": items}


def _any(items: list[Filter]) -> Filter:
    return items[0] if len(items) == 1 else {"orAll": items}


def _eq(key: str, value: str) -> Filter:
    return {"equals": {"key": key, "value": value}}


def retrieval_filter(ctx: Context) -> Filter:
    u = org().users[ctx.user]
    classes: list[Filter] = [_eq("classification", "internal")]
    if u.role == "risk":
        classes.append(_eq("classification", "confidential"))
    else:
        classes.append(_all([_eq("classification", "confidential"), _eq("desk", u.desk)]))
    if u.insider_lists:
        classes.append(_all([_eq("classification", "inside_information"), {"in": {"key": "insider_list", "value": list(u.insider_lists)}}]))
    scopes: list[Filter] = [_eq("scope", "application"), _all([_eq("scope", "user"), _eq("owner", ctx.user)])]
    if ctx.chat:
        scopes.append(_all([_eq("scope", "chat"), _eq("chat", ctx.chat)]))
    if ctx.agent:
        scopes.append(_all([_eq("scope", "agent"), _eq("agent", ctx.agent)]))
    return _all([_any(classes), _any(scopes)])


def evaluate(f: Filter, meta: dict[str, str]) -> bool:
    """Bedrock retrieval-filter semantics for the operators this module emits."""
    ((op, arg),) = f.items()
    if op == "andAll":
        return all(evaluate(x, meta) for x in arg)
    if op == "orAll":
        return any(evaluate(x, meta) for x in arg)
    if op == "equals":
        return meta.get(arg["key"]) == arg["value"]
    if op == "notEquals":
        return meta.get(arg["key"]) != arg["value"]
    if op == "in":
        return meta.get(arg["key"]) in arg["value"]
    raise ValueError(f"unsupported filter operator {op}")


_COLUMNS = {"classification", "scope", "desk", "owner", "chat", "agent", "insider_list"}


def to_sql(f: Filter, params: list[Any]) -> str:
    """Compile the filter to a parameterised SQL predicate over the chunks table's metadata columns."""
    ((op, arg),) = f.items()
    if op in ("andAll", "orAll"):
        joiner = " AND " if op == "andAll" else " OR "
        return "(" + joiner.join(to_sql(x, params) for x in arg) + ")"
    key = arg["key"]
    if key not in _COLUMNS:
        raise ValueError(f"unknown metadata key {key}")
    if op == "equals":
        params.append(arg["value"])
        return f"{key} = %s"
    if op == "notEquals":
        params.append(arg["value"])
        return f"{key} <> %s"
    if op == "in":
        params.append(list(arg["value"]))
        return f"{key} = ANY(%s)"
    raise ValueError(f"unsupported filter operator {op}")

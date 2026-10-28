"""The desk's tools: one definition each, used by the in-process gateway, the MCP server, the
AWS Lambda handlers and the AgentCore Gateway target schemas, so they cannot drift apart."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from powerdesk.quant import book as qb
from powerdesk.quant import market as qm
from powerdesk.settings import book

DataClass = Literal["market", "book", "knowledge"]
Zone = Literal["DE-LU", "FR", "NL"]
Day = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="Local delivery date, YYYY-MM-DD")]
EndDay = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="First local delivery date NOT included, YYYY-MM-DD")]
Month = Annotated[str, Field(pattern=r"^\d{4}-\d{2}$", description="Delivery month, YYYY-MM")]


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ZonePeriod(Args):
    zone: Zone
    start: Day
    end: EndDay


class PriceStatsArgs(ZonePeriod):
    kind: Literal["day_ahead", "intraday", "imbalance"] = "day_ahead"
    product: Literal["base", "peak", "offpeak"] = "base"


class TechPeriod(ZonePeriod):
    technology: Literal["solar", "wind_onshore", "wind_offshore", "wind"]


class PpaArgs(Args):
    ppa: Annotated[str, Field(description="PPA id, for example PPA-DE-SOL-01")]
    start: Day
    end: EndDay


class ImbalanceArgs(PpaArgs):
    extra_error_pct: Annotated[float, Field(ge=0, le=50, description="Stress: extra forecast error as a share of output, percent")] = 0.0


class PortfolioArgs(Args):
    start: Day
    end: EndDay
    books: Annotated[list[str] | None, Field(description="Books to include; default: every book you may see")] = None


class BatteryArgs(Args):
    asset: Annotated[str, Field(description="Battery id, for example BESS-DE-01")]
    start: Day
    end: EndDay


class HedgeArgs(Args):
    month: Month
    books: Annotated[list[str] | None, Field(description="Books to include; default: every hedging book you may see")] = None


class NoArgs(Args):
    pass


class SearchArgs(Args):
    query: Annotated[str, Field(min_length=3, max_length=500)]
    scopes: Annotated[
        list[Literal["application", "agent", "user", "chat"]] | None,
        Field(description="Knowledge scopes to search; default all four"),
    ] = None
    k: Annotated[int, Field(ge=1, le=8)] = 4


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    data_class: DataClass
    args: type[Args]
    run: Callable[[Any, Any], dict]  # (call context, validated args) -> result
    books: Callable[[Any, Any], list[str]] | None = None  # books a call reads, for read_book checks


def _ppa_book(_ctx: Any, a: Any) -> list[str]:
    p = book().ppas.get(a.ppa)
    return [p.book] if p else []


def _battery_book(_ctx: Any, a: Any) -> list[str]:
    b = book().batteries.get(a.asset)
    return [b.book] if b else []


def _requested_books(kind: str) -> Callable[[Any, Any], list[str]]:
    def f(ctx: Any, a: Any) -> list[str]:
        if a.books:
            return list(a.books)
        return [b for b in ctx.readable_books if book().books[b].kind == kind]

    return f


def _assets(ctx: Any, _a: Any) -> dict:
    cfg = book()
    readable = set(ctx.readable_books)
    return {
        "books": sorted(readable),
        "ppas": [
            {"ppa": k, "book": v.book, "zone": v.zone, "technology": v.tech, "mw": v.mw, "strike": v.strike, "negative_clause": v.negative_clause}
            for k, v in sorted(cfg.ppas.items())
            if v.book in readable
        ],
        "batteries": [{"asset": k, "book": v.book, "zone": v.zone, "mw": v.mw, "mwh": v.mwh} for k, v in sorted(cfg.batteries.items()) if v.book in readable],
        "units": {"mw": "MW", "strike": "EUR/MWh", "mwh": "MWh"},
    }


TOOLS: list[ToolSpec] = [
    ToolSpec(
        "price_stats",
        "Average, minimum and maximum (with local times) of day-ahead, intraday or imbalance prices for a bidding zone and period; base, peak or off-peak.",
        "market",
        PriceStatsArgs,
        lambda _c, a: qm.price_stats(a.zone, a.start, a.end, a.kind, a.product),
    ),
    ToolSpec(
        "negative_prices",
        "Negative day-ahead quarter hours in a zone and period: count, hours, share, longest run, by month.",
        "market",
        ZonePeriod,
        lambda _c, a: qm.negative_prices(a.zone, a.start, a.end),
    ),
    ToolSpec(
        "capture_price",
        "Capture price and capture rate of solar or wind in a zone: generation-weighted day-ahead price against the baseload average.",
        "market",
        TechPeriod,
        lambda _c, a: qm.capture_price(a.zone, a.technology, a.start, a.end),
    ),
    ToolSpec(
        "price_drivers",
        "What drove day-ahead prices in a zone and period: residual load, renewables, gas and carbon, which block of the supply curve set the price, and the lowest and highest quarter hours.",
        "market",
        ZonePeriod,
        lambda _c, a: qm.price_drivers(a.zone, a.start, a.end),
    ),
    ToolSpec(
        "forecast_error",
        "Day-ahead forecast error of solar or wind generation in a zone: bias, mean absolute error, worst miss.",
        "market",
        TechPeriod,
        lambda _c, a: qm.forecast_error(a.zone, a.technology, a.start, a.end),
    ),
    ToolSpec("list_book_assets", "The books, PPAs and batteries you may see.", "book", NoArgs, lambda c, a: _assets(c, a), lambda c, _a: list(c.readable_books)),
    ToolSpec(
        "ppa_valuation",
        "Value of one pay-as-produced PPA over a period: volume, capture price, P&L against the strike, shape discount, energy curtailed by a negative-price clause, imbalance cost.",
        "book",
        PpaArgs,
        lambda _c, a: qb.ppa_valuation(a.ppa, a.start, a.end),
        _ppa_book,
    ),
    ToolSpec(
        "ppa_portfolio",
        "All PPAs in your origination books over a period, with totals.",
        "book",
        PortfolioArgs,
        lambda c, a: qb.ppa_portfolio(_requested_books("ppa")(c, a), a.start, a.end),
        _requested_books("ppa"),
    ),
    ToolSpec(
        "imbalance_exposure",
        "Imbalance cost of a PPA's forecast errors at imbalance prices, and a stress with extra forecast error.",
        "book",
        ImbalanceArgs,
        lambda _c, a: qb.imbalance_exposure(a.ppa, a.start, a.end, a.extra_error_pct),
        _ppa_book,
    ),
    ToolSpec(
        "battery_backtest",
        "Day-ahead arbitrage backtest of a battery: perfect-foresight optimum (linear programme) against a simple daily charge/discharge rule.",
        "book",
        BatteryArgs,
        lambda _c, a: qb.battery_backtest(a.asset, a.start, a.end),
        _battery_book,
    ),
    ToolSpec(
        "hedge_report",
        "Month futures in your trading books settled against the month's day-ahead average, with P&L and hedge ratio against PPA output.",
        "book",
        HedgeArgs,
        lambda c, a: qb.hedge_report(_requested_books("hedges")(c, a), a.month),
        _requested_books("hedges"),
    ),
    ToolSpec(
        "search_knowledge",
        "Search the desk's knowledge: market rules, playbooks, research notes and documents you may read, across application, agent, user and chat scopes.",
        "knowledge",
        SearchArgs,
        lambda c, a: c.search(a.query, a.scopes, a.k),
    ),
]

BY_NAME = {t.name: t for t in TOOLS}


def mcp_schema(t: ToolSpec) -> dict:
    """Full JSON Schema of a tool's arguments (MCP tools/list)."""
    s = t.args.model_json_schema()
    s.pop("title", None)
    return s


_ALLOWED = {"type", "properties", "required", "items", "description"}


def _simplify(s: dict, defs: dict) -> dict:
    if "$ref" in s:
        return _simplify(defs[s["$ref"].split("/")[-1]], defs)
    if "anyOf" in s:  # Optional[X]: keep X
        non_null = [x for x in s["anyOf"] if x.get("type") != "null"]
        merged = {**_simplify(non_null[0], defs), **({"description": s["description"]} if "description" in s else {})}
        return merged
    out: dict = {}
    notes = []
    if "enum" in s:
        notes.append("one of: " + ", ".join(str(v) for v in s["enum"]))
    if "const" in s:
        notes.append(f"must be {s['const']}")
    if "pattern" in s:
        notes.append(f"format {s['pattern']}")
    if "default" in s:
        notes.append(f"default {s['default']}")
    for k in ("minimum", "maximum", "minLength", "maxLength"):
        if k in s:
            notes.append(f"{k} {s[k]}")
    typ = s.get("type", "string" if "enum" in s else None)
    if typ:
        out["type"] = typ
    desc = " ".join(x for x in [s.get("description", ""), "; ".join(notes)] if x)
    if desc:
        out["description"] = desc
    if typ == "object":
        out["properties"] = {k: _simplify(v, defs) for k, v in s.get("properties", {}).items()}
        if s.get("required"):
            out["required"] = list(s["required"])
    if typ == "array":
        out["items"] = _simplify(s.get("items", {"type": "string"}), defs)
    return {k: v for k, v in out.items() if k in _ALLOWED}


def agentcore_schema(t: ToolSpec) -> dict:
    """The tool as an AgentCore Gateway inline tool definition. The gateway accepts a JSON Schema
    subset (type, properties, required, items, description), so enums, patterns and bounds are
    folded into descriptions; the Lambda validates the full schema again."""
    s = t.args.model_json_schema()
    return {"name": t.name, "description": t.description, "inputSchema": _simplify(s, s.get("$defs", {}))}

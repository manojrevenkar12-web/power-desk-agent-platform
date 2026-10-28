"""A simulated model that speaks the Bedrock Converse API, for CI and offline runs.

It plans from the request it is given and nothing else: the question, the tools on offer, the
skill catalogue in the system prompt and the tool results in the conversation. It never imports
the market model, the book, the gateway or the knowledge base. Two kinds of fault can be switched
on (config/sim.yaml) so the platform's defences have something to catch:

- `derived_number_rate`: the model adds a number it computed itself (a difference of two tool
  values), which no tool returned. The grounding check must catch it.
- `obey_injected_instructions`: the model follows instructions it finds in documents. Policy at
  the gateway must stop whatever it then tries.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], start=1)}
FIRST, END = "2026-06-01", "2026-10-01"


@dataclass
class Plan:
    skill: str | None
    steps: list[tuple[str, dict[str, Any]]]


def _zone(q: str) -> str:
    ql = q.lower()
    if re.search(r"\b(france|french|fr)\b", ql):
        return "FR"
    if re.search(r"\b(netherlands|dutch|nl)\b", ql):
        return "NL"
    return "DE-LU"


def _tech(q: str) -> str:
    ql = q.lower()
    if "offshore" in ql:
        return "wind_offshore"
    if "onshore" in ql:
        return "wind_onshore"
    if "wind" in ql:
        return "wind"
    return "solar"


def _next_day(d: str) -> str:
    y, m, dd = (int(x) for x in d.split("-"))
    days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    dd += 1
    if dd > days[m - 1]:
        dd, m = 1, m + 1
        if m > 12:
            m, y = 1, y + 1
    return f"{y:04d}-{m:02d}-{dd:02d}"


def _period(q: str) -> tuple[str, str]:
    ql = q.lower()
    iso = re.findall(r"\b(2026-\d{2}-\d{2})\b", q)
    if len(iso) >= 2:
        return iso[0], iso[1]
    if len(iso) == 1:
        return iso[0], _next_day(iso[0])
    rng = re.search(r"\b(\d{1,2})\s*(?:to|-|–|and)\s*(\d{1,2})\s+(" + "|".join(MONTHS) + r")\b", ql)
    if rng:
        m = MONTHS[rng.group(3)]
        start = f"2026-{m:02d}-{int(rng.group(1)):02d}"
        return start, _next_day(f"2026-{m:02d}-{int(rng.group(2)):02d}")
    day = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(MONTHS) + r")\b|\b(" + "|".join(MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b(?!\s*,?\s*\d{4})", ql)
    if day:
        d = int(day.group(1) or day.group(4))
        m = MONTHS[day.group(2) or day.group(3)]
        s = f"2026-{m:02d}-{d:02d}"
        return s, _next_day(s)
    months = [MONTHS[m] for m in re.findall(r"\b(" + "|".join(MONTHS) + r")\b", ql)]
    if months:
        lo, hi = min(months), max(months)
        return f"2026-{lo:02d}-01", (f"2026-{hi + 1:02d}-01" if hi < 12 else "2027-01-01")
    if re.search(r"\bq3\b|third quarter", ql):
        return "2026-07-01", END
    return FIRST, END


def _month(q: str) -> str:
    s, _ = _period(q)
    return s[:7]


def _ppa(q: str) -> str | None:
    m = re.search(r"\bPPA-[A-Z]{2}-[A-Z]{3}-\d{2}\b", q)
    return m.group(0) if m else None


def _asset(q: str) -> str | None:
    m = re.search(r"\bBESS-[A-Z]{2}-\d{2}\b", q)
    return m.group(0) if m else None


def plan(q: str) -> Plan:
    ql = q.lower()
    zone, (start, end) = _zone(q), _period(q)
    zp = {"zone": zone, "start": start, "end": end}
    books = sorted(set(re.findall(r"\b(?:trading|origination|vpp)-(?:de|fr|nl)\b", ql)))
    if re.search(r"outage|nordheide|\bk7\b|inside information|unplanned|remit", ql):
        return Plan(None, [("search_knowledge", {"query": q})])
    if "hedge" in ql or "hedging" in ql or "over-hedged" in ql:
        hedge = {"month": _month(q), **({"books": books} if books else {})}
        return Plan("hedge-position-check", [("hedge_report", hedge), ("search_knowledge", {"query": "hedge ratio target front month"})])
    if re.search(r"battery|bess|\bvpp\b", ql):
        a = _asset(q)
        steps = [("battery_backtest", {"asset": a, "start": start, "end": end})] if a else [("list_book_assets", {}), ("battery_backtest@first", {"start": start, "end": end})]
        return Plan("battery-backtest-review", steps)
    if re.search(r"\bnotes?\b|pipeline|read me|newsletter|commentary", ql):
        return Plan(None, [("search_knowledge", {"query": q})])
    ppa = _ppa(q)
    if ppa and re.search(r"imbalance|forecast error|balancing|stress", ql):
        pct = re.search(r"(\d+(?:\.\d+)?)\s?(?:%|percent)", ql)
        return Plan(
            "imbalance-risk-check",
            [
                ("search_knowledge", {"query": "imbalance risk check methodology stress", "scopes": ["agent"]}),
                ("imbalance_exposure", {"ppa": ppa, "start": start, "end": end, "extra_error_pct": float(pct.group(1)) if pct else 5.0}),
            ],
        )
    if "forecast error" in ql:
        return Plan("imbalance-risk-check", [("forecast_error", {**zp, "technology": _tech(q)})])
    if ppa:
        return Plan("ppa-performance-report", [("ppa_valuation", {"ppa": ppa, "start": start, "end": end})])
    if re.search(r"\bppas?\b|portfolio|origination", ql):
        port = {"start": start, "end": end, **({"books": books} if books else {})}
        return Plan("ppa-performance-report", [("ppa_portfolio", port), ("ppa_valuation@worst", {"start": start, "end": end})])
    if re.search(
        r"section 51|eeg|rebap|imbalance settlement|methodology|policy|strategy|pipeline|my notes|glossary|what is|what does|how does|rules?\b|broker|newsletter|commentary|research note", ql
    ):
        return Plan(None, [("search_knowledge", {"query": q})])
    if "negative" in ql:
        return Plan("negative-price-review", [("negative_prices", zp), ("capture_price", {**zp, "technology": "solar"})])
    if "capture" in ql or "cannibal" in ql:
        return Plan("negative-price-review", [("capture_price", {**zp, "technology": _tech(q)})])
    stats_args = {
        **zp,
        "kind": "intraday" if "intraday" in ql else ("imbalance" if "imbalance price" in ql else "day_ahead"),
        "product": "offpeak" if re.search(r"off-?peak", ql) else ("peak" if "peak" in ql else "base"),
    }
    if re.search(r"\bwhy\b|drove|driver|explain|what set|cause", ql):
        steps = [("price_drivers", zp)]
        if re.search(r"average|highest|lowest|maximum|minimum", ql):
            steps.append(("price_stats", stats_args))
        return Plan("explain-price-move", steps)
    if re.search(r"price|average|highest|lowest|maximum|minimum|spread", ql):
        return Plan("explain-price-move", [("price_stats", stats_args)])
    return Plan(None, [("search_knowledge", {"query": q})])


def _fmt(v: Any, unit: str | None = None) -> str:
    if isinstance(v, float) and v.is_integer() and abs(v) >= 1000:
        s = f"{v:,.0f}"
    elif isinstance(v, float) and v.is_integer():
        s = f"{v:.0f}"
    else:
        s = f"{v:,}" if isinstance(v, int) else str(v)
    u = {"EUR/MWh": " EUR/MWh", "EUR": " EUR", "%": "%", "MWh": " MWh", "MW": " MW", "GW": " GW", "h": " h", "TWh": " TWh", "EUR/t": " EUR/t", "EUR/MW/day": " EUR/MW/day"}.get(unit or "", "")
    return f"{s}{u}"


def describe(name: str, c: dict[str, Any]) -> list[str]:
    """Sentences for one tool result, numbers copied as returned."""
    u = c.get("units", {})
    f = lambda k: _fmt(c[k], u.get(k))  # noqa: E731
    p = c.get("period", {})
    per = f"from {p.get('start')} to {p.get('end_exclusive')} (end excluded)" if p else ""
    if name == "price_stats":
        return [
            f"{c['zone']} {c['product']} {c['kind'].replace('_', '-')} prices {per} averaged {f('average')}.",
            f"The lowest quarter hour was {f('minimum')} at {c['minimum_at']} and the highest {f('maximum')} at {c['maximum_at']}.",
        ]
    if name == "negative_prices":
        return [
            f"{c['zone']} had {f('negative_hours')} of negative day-ahead prices {per} ({f('negative_intervals')} quarter hours, {f('share_of_intervals')} of intervals).",
            f"The longest negative run lasted {f('longest_run_hours')} and the lowest price was {f('lowest_price')}.",
        ]
    if name == "capture_price":
        return [
            f"{c['technology'].replace('_', ' ').capitalize()} in {c['zone']} captured {f('capture_price')} {per}, against a baseload average of {f('baseload_price')}: a capture rate of {f('capture_rate')}.",
            f"{f('generation_in_negative_hours')} of its generation fell in negative quarter hours.",
        ]
    if name == "price_drivers":
        lo, hi = c["lowest"], c["highest"]
        lu = {"EUR/MWh": " EUR/MWh"}
        return [
            f"{c['zone']} day-ahead prices {per} averaged {f('average_price')}, with residual load averaging {f('average_residual_load_gw')} and renewables forecast at {f('average_renewables_forecast_gw')}.",
            f"The lowest price, {lo['price']}{lu['EUR/MWh']} at {lo['at']}, came with residual load of {lo['residual_load_gw']} GW and {lo['renewables_forecast_gw']} GW of renewables; it was set by {lo['price_setter']}.",
            f"The highest, {hi['price']}{lu['EUR/MWh']} at {hi['at']}, was set by {hi['price_setter']} with residual load at {hi['residual_load_gw']} GW.",
            f"Gas averaged {f('gas_ttf')} and carbon {f('carbon_eua')}.",
        ]
    if name == "forecast_error":
        return [
            f"The day-ahead {c['technology'].replace('_', ' ')} forecast in {c['zone']} {per} had a bias of {f('bias_mw')} and a mean absolute error of {f('mean_absolute_error_mw')}; the worst miss was {f('worst_miss_mw')} at {c['worst_miss_at']}."
        ]
    if name == "ppa_valuation":
        out = [
            f"{c['ppa']} delivered {f('volume_mwh')} {per} at a capture price of {f('capture_price')} against a strike of {f('strike')}, for a P&L of {f('pnl_eur')} ({f('pnl_per_mwh')}).",
            f"Its shape discount to baseload was {f('shape_discount')} and its imbalance cost {f('imbalance_cost_eur')}.",
        ]
        if c.get("curtailed_by_negative_clause_mwh"):
            out.append(f"The negative-price clause removed {f('curtailed_by_negative_clause_mwh')} of delivery.")
        return out
    if name == "ppa_portfolio":
        return [
            f"Across {', '.join(c['books'])}, the PPAs delivered {f('total_volume_mwh')} {per} at a volume-weighted capture price of {f('volume_weighted_capture_price')}, for a total P&L of {f('total_pnl_eur')} and imbalance cost of {f('total_imbalance_cost_eur')}."
        ]
    if name == "imbalance_exposure":
        return [
            f"{c['ppa']} paid {f('realised_imbalance_cost_eur')} in imbalance cost {per}, with a mean absolute gap of {f('mean_absolute_spread')} between imbalance and day-ahead prices.",
            f"A stress of {f('stress_extra_error_pct')} extra forecast error would add {f('stress_additional_cost_eur')}; this is a sensitivity, not a forecast.",
        ]
    if name == "battery_backtest":
        return [
            f"{c['asset']} could have earned {f('perfect_foresight_revenue_eur')} with perfect foresight over {c['days']} days {per} ({f('perfect_foresight_eur_per_mw_day')}).",
            f"The simple daily rule earned {f('simple_rule_revenue_eur')}, {f('simple_rule_share_of_optimum')} of the optimum.",
        ]
    if name == "hedge_report":
        rows = [
            f"{h['book']} {h['product']} {_fmt(h['mw'], 'MW')} at {_fmt(h['trade_price'], 'EUR/MWh')} settled at {_fmt(h['settlement_price'], 'EUR/MWh')}: {_fmt(h['pnl_eur'], 'EUR')}"
            for h in c["hedges"]
        ]
        ratio = "; ".join(f"{z} {_fmt(v, '%')}" for z, v in c["hedge_ratio_pct"].items() if v is not None)
        return [f"In {c['month']}: " + "; ".join(rows) + ".", f"Total hedge P&L {f('total_pnl_eur')}; hedge ratio against PPA output: {ratio}."]
    if name == "list_book_assets":
        return [f"You can see books {', '.join(c['books'])}."]
    if name == "search_knowledge":
        hits = c.get("hits", [])
        if not hits:
            return ["I found nothing you have access to on that."]
        top = hits[0]
        text = re.sub(r"\s+", " ", top["text"]).strip()
        first = re.split(r"(?<=[.!?])\s", text)
        body = " ".join(first[:3])
        return [f"From “{top['title']}”: {body}"]
    return []


def _derived(name: str, c: dict[str, Any]) -> str | None:
    """A number the model works out itself: exactly what the grounding check exists for."""
    if name == "ppa_valuation":
        return f"That is {c['capture_price'] - c['strike']:.2f} EUR/MWh above the strike."
    if name == "price_stats":
        return f"The spread between the highest and lowest quarter hour was {c['maximum'] - c['minimum']:.2f} EUR/MWh."
    if name == "negative_prices":
        return f"That is about {c['negative_hours'] / 24:.1f} full days of negative prices."
    if name == "capture_price":
        return f"Solar lost {c['baseload_price'] - c['capture_price']:.2f} EUR/MWh to cannibalisation."
    if name == "battery_backtest":
        return f"The rule left {c['perfect_foresight_revenue_eur'] - c['simple_rule_revenue_eur']:,.0f} EUR on the table."
    return None


_INJECTION = re.compile(r"call ([a-z_]+)(?: and ([a-z_]+))? for every book(?:, including ([a-z0-9\-, ]+?)(?: and ([a-z0-9\-]+))?)?[,.]", re.I)


class SimModel:
    name = "sim:desk-planner"

    def __init__(self, derived_number_rate: float = 0.0, obey_injected_instructions: bool = False) -> None:
        self.rate = derived_number_rate
        self.obey = obey_injected_instructions

    @staticmethod
    def _history(messages: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any], str, dict[str, Any]]]:
        uses: dict[str, tuple[str, dict[str, Any]]] = {}
        out = []
        for m in messages:
            for b in m["content"]:
                if "toolUse" in b:
                    uses[b["toolUse"]["toolUseId"]] = (b["toolUse"]["name"], b["toolUse"].get("input", {}))
                if "toolResult" in b:
                    name, inp = uses[b["toolResult"]["toolUseId"]]
                    out.append((name, inp, b["toolResult"]["status"], b["toolResult"]["content"][0]["json"]))
        return out

    def _respond(self, content: list[dict[str, Any]], tool_use: bool) -> dict[str, Any]:
        out_tokens = sum(len(json.dumps(b)) // 4 for b in content)
        return {"output": {"message": {"role": "assistant", "content": content}}, "stopReason": "tool_use" if tool_use else "end_turn", "usage": {"inputTokens": 0, "outputTokens": out_tokens}}

    def _use(self, name: str, args: dict[str, Any], n: int) -> dict[str, Any]:
        return self._respond([{"toolUse": {"toolUseId": f"tu-{n}-{name}", "name": name, "input": args}}], True)

    def converse(self, request: dict[str, Any]) -> dict[str, Any]:
        msgs = request["messages"]
        question = msgs[0]["content"][0]["text"]
        history = self._history(msgs)
        offered = {t["toolSpec"]["name"] for t in request["toolConfig"]["tools"] if "toolSpec" in t}
        last = msgs[-1]["content"][0] if msgs[-1]["role"] == "user" else {}
        # 1. a grounding complaint: drop the sentences with the listed numbers and answer again
        if "text" in last and last["text"].startswith("Grounding check:"):
            prev = next(b["text"] for m in reversed(msgs) if m["role"] == "assistant" for b in m["content"] if "text" in b)
            bad = re.search(r"documents?: (.*?)\. Remove", last["text"])
            listed = [x.strip() for x in bad.group(1).split(";")] if bad else []
            kept = [s for s in re.split(r"(?<=[.!?])\s+", prev) if not any(x and x in s for x in listed)]
            return self._respond([{"text": " ".join(kept)}], False)
        p = plan(question)
        n = len(history)
        # 2. load the skill first
        if p.skill and not any(h[0] == "load_skill" for h in history) and "load_skill" in offered:
            return self._use("load_skill", {"name": p.skill}, n)
        # 3. a compromised model would act on instructions it read in a document
        if self.obey:
            for name, _inp, status, c in history:
                if name != "search_knowledge" or status != "success":
                    continue
                for h in c.get("hits", []):
                    m = _INJECTION.search(re.sub(r"\s+", " ", h["text"]))
                    if not m:
                        continue
                    books = [b.strip() for b in re.split(r",| and ", (m.group(3) or "") + "," + (m.group(4) or "")) if b.strip()]
                    for tool in [t for t in (m.group(1), m.group(2)) if t]:
                        args = {"start": FIRST, "end": END, "books": books} if tool == "ppa_portfolio" else {"month": "2026-08", "books": books}
                        if not any(hh[0] == tool and hh[1].get("books") == books for hh in history):
                            return self._use(tool, args, n)
        # 4. the next planned step not yet done
        done = [(h[0], json.dumps(h[1], sort_keys=True)) for h in history]
        for tool, args in p.steps:
            name = tool.split("@")[0]
            if tool.endswith("@first"):
                assets = next((h[3] for h in history if h[0] == "list_book_assets" and h[2] == "success"), None)
                if assets is None or not assets.get("batteries"):
                    continue
                name, args = "battery_backtest", {**args, "asset": assets["batteries"][0]["asset"]}
            if tool.endswith("@worst"):
                port = next((h[3] for h in history if h[0] == "ppa_portfolio" and h[2] == "success"), None)
                if port is None:
                    continue
                worst = min(port["ppas"], key=lambda r: r["pnl_eur"])
                name, args = "ppa_valuation", {**args, "ppa": worst["ppa"]}
            if (name, json.dumps(args, sort_keys=True)) in done:
                continue
            if name not in offered:
                continue  # not on offer to this user: the answer will say so
            return self._use(name, args, n)
        # 5. answer from what came back
        sentences: list[str] = []
        for name, _inp, status, c in history:
            if name in ("load_skill", "list_book_assets") and status == "success":
                continue
            if status != "success":
                if c.get("denied_by"):
                    sentences.append(f"You do not have access to that: {c.get('error')}.")
                else:
                    sentences.append(f"The {name} tool could not answer: {c.get('error')}.")
                continue
            sentences += describe(name, c)
        missing = [t.split("@")[0] for t, _ in p.steps if t.split("@")[0] not in offered and not t.endswith(("@first", "@worst"))]
        if missing and not any(h[0] in missing for h in history):
            sentences.append(f"I cannot use {', '.join(sorted(set(missing)))} for you, so I cannot answer that part.")
        h = int(hashlib.sha256(question.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        if h < self.rate:
            for name, _inp, status, c in history:
                d = _derived(name, c) if status == "success" else None
                if d:
                    sentences.append(d)
                    break
        if not sentences:
            sentences = ["I could not find anything to answer that with."]
        return self._respond([{"text": " ".join(sentences)}], False)

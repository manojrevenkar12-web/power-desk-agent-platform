"""Numeric grounding: every figure in an answer must trace to a tool result or a document the user
was shown in the same turn.

A trading desk acts on numbers. Language models round, re-derive and occasionally invent them.
The verifier extracts each number the answer states (with its unit when one is written next to
it), looks for evidence with the same value at the stated precision and a compatible unit, and
reports what it could not trace. The runtime sends untraced numbers back to the model once; if
they survive, the sentences that carry them are removed before the user sees the answer.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

UNIT_ALIASES = {
    "€/mw/day": "EUR/MW/day",
    "eur/mw/day": "EUR/MW/day",
    "€/mwh": "EUR/MWh",
    "eur/mwh": "EUR/MWh",
    "euros per megawatt hour": "EUR/MWh",
    "€/t": "EUR/t",
    "eur/t": "EUR/t",
    "€": "EUR",
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "%": "%",
    "percent": "%",
    "per cent": "%",
    "mwh": "MWh",
    "gwh": "GWh",
    "twh": "TWh",
    "mw": "MW",
    "gw": "GW",
    "h": "h",
    "hours": "h",
    "hour": "h",
    "days": "count",
    "quarter hours": "count",
    "intervals": "count",
    "ms": "ms",
}
# units that are the same quantity at another scale: (unit, factor to the base unit)
SCALE = {"GWh": ("MWh", 1e3), "TWh": ("MWh", 1e6), "GW": ("MW", 1e3), "kEUR": ("EUR", 1e3), "mEUR": ("EUR", 1e6)}

_NUM = re.compile(
    r"(?P<pre>€\s?)?(?P<sign>[-−–]\s?)?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<mult>\s?(?:k|thousand|million|m)\b)?"
    r"(?P<unit>\s?(?:€/MW/day|EUR/MW/day|€/MWh|EUR/MWh|euros per megawatt hour|€/t|EUR/t|%|percent|per cent|MWh|GWh|TWh|MW|GW|EUR|euros?|hours?|days|quarter hours|intervals|ms|h)\b|\s?%)?",
    re.I,
)
_SKIP = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2})?\b"),  # dates and timestamps
    re.compile(r"\b\d{4}-\d{2}\b"),  # months
    re.compile(r"\b\d{1,2}:\d{2}\b"),  # clock times
    re.compile(r"\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)(?:\s+\d{4})?\b", re.I),
    re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b", re.I),
    re.compile(r"\b(?:19|20)\d{2}\b"),  # years
    re.compile(r"\b[A-Z]{2,}(?:-[A-Z0-9]+)+\b"),  # identifiers: PPA-DE-SOL-01, BESS-NL-03, DE-LU
    re.compile(r"§\s?\d+[a-z]?|section \d+[a-z]?", re.I),
    re.compile(r"\b(?:Q[1-4]|W\d{1,2}|week \d{1,2})\b", re.I),
    re.compile(r"\b\d+(?:-minute|-hour|-day|-year)\b", re.I),
]


@dataclass(frozen=True)
class Evidence:
    id: str
    value: float
    unit: str | None
    source: str  # call id or document id
    path: str


@dataclass(frozen=True)
class StatedNumber:
    text: str
    value: float
    decimals: int
    unit: str | None
    start: int
    end: int


@dataclass
class Report:
    numbers: list[tuple[StatedNumber, Evidence | None, str]] = field(default_factory=list)

    @property
    def ungrounded(self) -> list[StatedNumber]:
        return [n for n, e, _ in self.numbers if e is None]

    @property
    def ok(self) -> bool:
        return not self.ungrounded

    def as_dict(self) -> list[dict[str, Any]]:
        return [
            {
                "text": n.text,
                "value": n.value,
                "unit": n.unit,
                "start": n.start,
                "end": n.end,
                "grounded": e is not None,
                "evidence": e.id if e else None,
                "source": e.source if e else None,
                "path": e.path if e else None,
                "reason": reason,
            }
            for n, e, reason in self.numbers
        ]


def norm_unit(u: str | None) -> str | None:
    if not u:
        return None
    return UNIT_ALIASES.get(u.strip().lower(), u.strip())


def _unit_for(path: str, units: dict[str, str]) -> str | None:
    parts = [p for p in re.split(r"[.\[\]]", path) if p and not p.isdigit()]
    for p in reversed(parts):
        if p in units:
            return units[p]
    return None


class Ledger:
    """Everything a model was shown in a turn that can back a number."""

    def __init__(self) -> None:
        self.items: list[Evidence] = []

    def add_tool_result(self, call_id: str, result: dict[str, Any]) -> None:
        units = result.get("units", {}) if isinstance(result.get("units"), dict) else {}

        def walk(v: Any, path: str) -> None:
            if isinstance(v, bool):
                return
            if isinstance(v, (int, float)):
                if math.isfinite(v):
                    self.items.append(Evidence(f"{call_id}:{path}", float(v), _unit_for(path, units), call_id, path))
            elif isinstance(v, dict):
                for k, x in v.items():
                    if k != "units":
                        walk(x, f"{path}.{k}" if path else str(k))
            elif isinstance(v, list):
                for i, x in enumerate(v):
                    walk(x, f"{path}[{i}]")
            elif isinstance(v, str):
                for n in extract(v):
                    self.items.append(Evidence(f"{call_id}:{path}", n.value, n.unit, call_id, path))

        walk(result, "")

    def add_text(self, source: str, text: str) -> None:
        for n in extract(text):
            self.items.append(Evidence(f"{source}@{n.start}", n.value, n.unit, source, f"text[{n.start}]"))


def extract(text: str) -> list[StatedNumber]:
    masked = text
    for rx in _SKIP:
        masked = rx.sub(lambda m: " " * len(m.group(0)), masked)
    out = []
    for m in _NUM.finditer(masked):
        raw = m.group("num")
        before = masked[max(0, m.start("num") - 1) : m.start("num")]
        if before.isalpha():
            continue  # part of a word or identifier
        val = float(raw.replace(",", ""))
        if m.group("sign"):
            val = -val
        mult = (m.group("mult") or "").strip().lower()
        unit = norm_unit(m.group("unit"))
        if m.group("pre") and not unit:
            unit = "EUR"
        if mult in ("k", "thousand"):
            val *= 1e3
        elif mult in ("million", "m") and unit != "MW":
            val *= 1e6
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        if mult:
            decimals = -3 if mult in ("k", "thousand") else -6
        out.append(StatedNumber(m.group(0).strip(), val, decimals, unit, m.start(), m.end()))
    return out


def _compatible(stated: str | None, ev: str | None) -> tuple[bool, float]:
    """Whether units agree, and the factor that turns the evidence value into the stated unit."""
    if stated is None or ev is None:
        return True, 1.0
    if stated == ev:
        return True, 1.0
    for big, (base, f) in SCALE.items():
        if stated == big and ev == base:
            return True, 1 / f
        if stated == base and ev == big:
            return True, f
    return False, 1.0


def _close(n: StatedNumber, target: float) -> bool:
    tol = 0.5 * 10 ** (-n.decimals) + 1e-9 * max(1.0, abs(target))
    # "a loss of EUR 202,440" may restate a negative P&L, so the sign may be dropped
    return any(abs(round(c, max(n.decimals, 0)) - n.value) <= tol or abs(c - n.value) <= tol for c in (target, -target))


def _matches(n: StatedNumber, e: Evidence) -> tuple[bool, str]:
    ok_unit, factor = _compatible(n.unit, e.unit)
    if ok_unit:
        return (True, "") if _close(n, e.value * factor) else (False, "value")
    return (False, "unit") if _close(n, e.value) else (False, "value")


def verify(answer: str, ledger: Ledger, exempt: list[str] | None = None) -> Report:
    """`exempt` holds texts whose numbers need no evidence (the user's own question)."""
    allowed = {n.value for t in exempt or [] for n in extract(t)}
    rep = Report()
    for n in extract(answer):
        if n.value in allowed:
            rep.numbers.append((n, Evidence("question", n.value, n.unit, "question", ""), "stated by the user"))
            continue
        found = None
        reason = "no tool result or document shows this number"
        for e in ledger.items:
            ok, why = _matches(n, e)
            if ok:
                found = e
                break
            if why == "unit":
                reason = "a tool shows this value, but in another unit"
        rep.numbers.append((n, found, "" if found else reason))
    return rep


def redact(answer: str, rep: Report) -> str:
    """Remove the sentences that carry untraced numbers."""
    bad = rep.ungrounded
    if not bad:
        return answer
    sentences = re.split(r"(?<=[.!?])\s+", answer)
    keep = []
    pos = 0
    for s in sentences:
        start = answer.find(s, pos)
        end = start + len(s)
        pos = end
        if any(start <= n.start < end for n in bad):
            continue
        keep.append(s)
    note = "Some figures were removed because no tool result or document supports them."
    return (" ".join(keep) + ("\n\n" if keep else "") + note).strip()

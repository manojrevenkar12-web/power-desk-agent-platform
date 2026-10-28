"""Documents and chunks. A document carries the metadata every access decision needs:
classification, scope (application, agent, user, chat) and the owner, desk, chat, agent or
insider list the scope refers to."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

from powerdesk.settings import ROOT

Classification = Literal["internal", "confidential", "inside_information"]
Scope = Literal["application", "agent", "user", "chat"]
META_KEYS = ("classification", "scope", "desk", "owner", "chat", "agent", "insider_list")

_INSTRUCTION = re.compile(
    r"\b(ignore (all |your |the )?(previous|prior|above) (instructions|rules)|disregard (your|the) (rules|instructions)|you are now|system prompt|this is authori[sz]ed)\b",
    re.I,
)


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    body: str
    meta: dict[str, str]
    hidden_text_removed: bool = False
    suspected_instructions: bool = False


@dataclass(frozen=True)
class Chunk:
    id: str
    doc_id: str
    title: str
    text: str
    meta: dict[str, str] = field(default_factory=dict)
    suspected_instructions: bool = False


def _meta(fm: dict) -> dict[str, str]:
    cls = fm.get("classification")
    scope = fm.get("scope")
    if cls not in ("internal", "confidential", "inside_information"):
        raise ValueError(f"document {fm.get('id')}: classification must be internal, confidential or inside_information")
    if scope not in ("application", "agent", "user", "chat"):
        raise ValueError(f"document {fm.get('id')}: unknown scope {scope}")
    meta = {k: str(fm.get(k, "") or "") for k in META_KEYS}
    required = {"confidential": "desk", "inside_information": "insider_list"}.get(cls)
    if required and not meta[required]:
        raise ValueError(f"document {fm.get('id')}: {cls} needs {required}")
    owner_key = {"user": "owner", "chat": "chat", "agent": "agent"}.get(scope)
    if owner_key and not meta[owner_key]:
        raise ValueError(f"document {fm.get('id')}: scope {scope} needs {owner_key}")
    return meta


def parse(text: str, *, overrides: dict[str, str] | None = None) -> Document:
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        raise ValueError("document needs YAML front matter")
    fm = yaml.safe_load(m.group(1)) or {}
    fm.update(overrides or {})
    body = m.group(2)
    # hidden text is a classic carrier for prompt injection: drop HTML comments, keep a flag
    cleaned = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    return Document(
        id=str(fm["id"]),
        title=str(fm["title"]),
        body=cleaned.strip(),
        meta=_meta(fm),
        hidden_text_removed=cleaned != body,
        suspected_instructions=bool(_INSTRUCTION.search(body)),
    )


def load_corpus(root: Path | None = None) -> list[Document]:
    base = root or ROOT / "kb/docs"
    docs = [parse(p.read_text(encoding="utf-8")) for p in sorted(base.rglob("*.md"))]
    ids = [d.id for d in docs]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate document ids in the corpus")
    return docs


def chunk(doc: Document, max_words: int = 110) -> list[Chunk]:
    """Paragraph chunks of at most `max_words`, each carrying its document's title and metadata."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", doc.body) if p.strip() and not p.strip().startswith("# ")]
    out: list[Chunk] = []
    buf: list[str] = []
    n = 0
    for p in paras:
        w = len(p.split())
        if buf and n + w > max_words:
            out.append(Chunk(f"{doc.id}#{len(out)}", doc.id, doc.title, "\n\n".join(buf), doc.meta, doc.suspected_instructions))
            buf, n = [], 0
        buf.append(p)
        n += w
    if buf:
        out.append(Chunk(f"{doc.id}#{len(out)}", doc.id, doc.title, "\n\n".join(buf), doc.meta, doc.suspected_instructions))
    return out

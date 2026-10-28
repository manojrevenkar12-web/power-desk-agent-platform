"""Embeddings. In AWS: Amazon Titan Text Embeddings V2 through Bedrock, inside the VPC. Offline and
in CI: a deterministic hashing embedder (word unigrams and bigrams), weaker but reproducible, so
retrieval tests do not depend on a network or a model download."""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Protocol

import numpy as np

_WORD = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")
_STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "which",
        "who",
        "why",
        "will",
        "with",
        "how",
        "do",
        "does",
        "did",
        "our",
        "we",
        "you",
        "your",
    ]
)


def words(text: str) -> list[str]:
    out = []
    for w in _WORD.findall(text.lower()):
        if w in _STOP:
            continue
        if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return out


class Embedder(Protocol):
    dim: int
    name: str

    def embed(self, texts: list[str]) -> np.ndarray: ...


class HashEmbedder:
    name = "hash-v1"

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim

    def _slot(self, token: str) -> tuple[int, float]:
        h = hashlib.blake2b(token.encode(), digest_size=8).digest()
        v = int.from_bytes(h, "big")
        return v % self.dim, 1.0 if (v >> 63) & 1 else -1.0

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            ws = words(t)
            grams = ws + [f"{a}_{b}" for a, b in zip(ws, ws[1:], strict=False)]
            counts: dict[str, int] = {}
            for g in grams:
                counts[g] = counts.get(g, 0) + 1
            for g, c in counts.items():
                j, s = self._slot(g)
                out[i, j] += s * (1 + math.log(c)) * (1.0 if "_" not in g else 0.7)
            n = np.linalg.norm(out[i])
            if n > 0:
                out[i] /= n
        return out


class BedrockTitanEmbedder:
    """amazon.titan-embed-text-v2:0, normalised, through the bedrock-runtime VPC endpoint."""

    name = "amazon.titan-embed-text-v2:0"

    def __init__(self, client: object, dim: int = 1024) -> None:
        self.client = client
        self.dim = dim

    def embed(self, texts: list[str]) -> np.ndarray:
        vecs = []
        for t in texts:
            body = json.dumps({"inputText": t[:8000], "dimensions": self.dim, "normalize": True})
            r = self.client.invoke_model(modelId=self.name, body=body, contentType="application/json", accept="application/json")  # type: ignore[attr-defined]
            vecs.append(json.loads(r["body"].read())["embedding"])
        return np.asarray(vecs, dtype=np.float32)

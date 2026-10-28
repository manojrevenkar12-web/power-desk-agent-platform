"""Chunk stores: in memory (tests, laptops) and PostgreSQL with pgvector (Aurora in AWS).
Both search with the same entitlement filter and return the same shape: (chunk, vector score,
keyword score)."""

from __future__ import annotations

import math
from collections import Counter
from typing import Protocol

import numpy as np

from powerdesk.kb.corpus import Chunk
from powerdesk.kb.embed import Embedder, words
from powerdesk.kb.entitlements import Filter, evaluate, to_sql


class Store(Protocol):
    def add(self, chunks: list[Chunk]) -> None: ...
    def remove_chat(self, chat: str) -> None: ...
    def vector_search(self, vec: np.ndarray, f: Filter, k: int) -> list[tuple[Chunk, float]]: ...
    def keyword_search(self, query: str, f: Filter, k: int) -> list[tuple[Chunk, float]]: ...


class MemoryStore:
    def __init__(self, embedder: Embedder) -> None:
        self.embedder = embedder
        self.chunks: list[Chunk] = []
        self.vecs = np.zeros((0, embedder.dim), dtype=np.float32)

    def add(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        self.chunks.extend(chunks)
        self.vecs = np.vstack([self.vecs, self.embedder.embed([f"{c.title}\n{c.text}" for c in chunks])])

    def remove_chat(self, chat: str) -> None:
        keep = [i for i, c in enumerate(self.chunks) if c.meta.get("chat") != chat]
        self.chunks = [self.chunks[i] for i in keep]
        self.vecs = self.vecs[keep]

    def _allowed(self, f: Filter) -> list[int]:
        return [i for i, c in enumerate(self.chunks) if evaluate(f, c.meta)]

    def vector_search(self, vec: np.ndarray, f: Filter, k: int) -> list[tuple[Chunk, float]]:
        idx = self._allowed(f)
        if not idx:
            return []
        scores = self.vecs[idx] @ vec
        order = np.argsort(-scores)[:k]
        return [(self.chunks[idx[i]], float(scores[i])) for i in order]

    def keyword_search(self, query: str, f: Filter, k: int) -> list[tuple[Chunk, float]]:
        """BM25 over the chunks the caller may see (k1 = 1.2, b = 0.75)."""
        idx = self._allowed(f)
        if not idx:
            return []
        docs = [words(f"{self.chunks[i].title} {self.chunks[i].text}") for i in idx]
        avg = sum(len(d) for d in docs) / len(docs)
        df: Counter[str] = Counter()
        for d in docs:
            df.update(set(d))
        q = set(words(query))
        scored = []
        for i, d in zip(idx, docs, strict=True):
            tf = Counter(d)
            s = 0.0
            for t in q:
                if tf[t]:
                    idf = math.log(1 + (len(docs) - df[t] + 0.5) / (df[t] + 0.5))
                    s += idf * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * len(d) / avg))
            if s > 0:
                scored.append((self.chunks[i], s))
        return sorted(scored, key=lambda x: -x[1])[:k]


SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS kb_chunks (
    id text PRIMARY KEY,
    doc_id text NOT NULL,
    title text NOT NULL,
    body text NOT NULL,
    classification text NOT NULL,
    scope text NOT NULL,
    desk text NOT NULL DEFAULT '',
    owner text NOT NULL DEFAULT '',
    chat text NOT NULL DEFAULT '',
    agent text NOT NULL DEFAULT '',
    insider_list text NOT NULL DEFAULT '',
    suspected_instructions boolean NOT NULL DEFAULT false,
    embedding vector({dim}) NOT NULL,
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', title || ' ' || body)) STORED
);
CREATE INDEX IF NOT EXISTS kb_chunks_hnsw ON kb_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS kb_chunks_tsv ON kb_chunks USING gin (tsv);
"""


class PgVectorStore:
    """PostgreSQL + pgvector. The same table works as the vector store behind an Amazon Bedrock
    knowledge base on Aurora PostgreSQL, where the metadata columns are what the retrieval
    filter refers to."""

    def __init__(self, conn: object, embedder: Embedder) -> None:
        from pgvector.psycopg import register_vector

        self.conn = conn
        self.embedder = embedder
        with conn.cursor() as cur:  # type: ignore[attr-defined]
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(conn)
        with conn.cursor() as cur:  # type: ignore[attr-defined]
            cur.execute(SCHEMA.format(dim=embedder.dim))
        conn.commit()  # type: ignore[attr-defined]

    def add(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        vecs = self.embedder.embed([f"{c.title}\n{c.text}" for c in chunks])
        with self.conn.cursor() as cur:  # type: ignore[attr-defined]
            for c, v in zip(chunks, vecs, strict=True):
                cur.execute(
                    """INSERT INTO kb_chunks (id, doc_id, title, body, classification, scope, desk, owner, chat, agent, insider_list, suspected_instructions, embedding)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (id) DO UPDATE SET body = EXCLUDED.body, embedding = EXCLUDED.embedding""",
                    (c.id, c.doc_id, c.title, c.text, *(c.meta[k] for k in ("classification", "scope", "desk", "owner", "chat", "agent", "insider_list")), c.suspected_instructions, v),
                )
        self.conn.commit()  # type: ignore[attr-defined]

    def remove_chat(self, chat: str) -> None:
        with self.conn.cursor() as cur:  # type: ignore[attr-defined]
            cur.execute("DELETE FROM kb_chunks WHERE scope = 'chat' AND chat = %s", (chat,))
        self.conn.commit()  # type: ignore[attr-defined]

    def _rows(self, sql: str, params: list) -> list[tuple]:
        with self.conn.cursor() as cur:  # type: ignore[attr-defined]
            cur.execute(sql, params)
            return cur.fetchall()

    @staticmethod
    def _chunk(r: tuple) -> Chunk:
        meta = dict(zip(("classification", "scope", "desk", "owner", "chat", "agent", "insider_list"), r[4:11], strict=True))
        return Chunk(r[0], r[1], r[2], r[3], meta, r[11])

    def vector_search(self, vec: np.ndarray, f: Filter, k: int) -> list[tuple[Chunk, float]]:
        params: list = []
        where = to_sql(f, params)
        rows = self._rows(
            f"""SELECT id, doc_id, title, body, classification, scope, desk, owner, chat, agent, insider_list, suspected_instructions,
                       1 - (embedding <=> %s) AS score
                FROM kb_chunks WHERE {where} ORDER BY embedding <=> %s LIMIT %s""",
            [vec, *params, vec, k],
        )
        return [(self._chunk(r), float(r[12])) for r in rows]

    def keyword_search(self, query: str, f: Filter, k: int) -> list[tuple[Chunk, float]]:
        params: list = []
        where = to_sql(f, params)
        rows = self._rows(
            f"""SELECT id, doc_id, title, body, classification, scope, desk, owner, chat, agent, insider_list, suspected_instructions,
                       ts_rank_cd(tsv, plainto_tsquery('english', %s)) AS score
                FROM kb_chunks WHERE {where} AND tsv @@ plainto_tsquery('english', %s) ORDER BY score DESC LIMIT %s""",
            [query, *params, query, k],
        )
        return [(self._chunk(r), float(r[12])) for r in rows]

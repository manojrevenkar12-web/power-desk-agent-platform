"""The pgvector store (the table shape behind Aurora) gives the same entitled results as the
in-memory store. Needs POWERDESK_TEST_DATABASE_URL (CI runs a pgvector service)."""

import os
import uuid

import pytest

from powerdesk.kb.embed import HashEmbedder
from powerdesk.kb.entitlements import retrieval_filter
from powerdesk.kb.search import KnowledgeBase
from powerdesk.kb.store import MemoryStore, PgVectorStore
from powerdesk.policy import Context
from powerdesk.settings import org

pytestmark = pytest.mark.db
URL = os.environ.get("POWERDESK_TEST_DATABASE_URL")


@pytest.fixture(scope="module")
def conn():
    if not URL:
        pytest.skip("POWERDESK_TEST_DATABASE_URL not set")
    import psycopg

    schema = f"t_{uuid.uuid4().hex[:8]}"
    c = psycopg.connect(URL, autocommit=False)
    with c.cursor() as cur:
        cur.execute(f"CREATE SCHEMA {schema}")
        cur.execute(f"SET search_path TO {schema}, public")
    c.commit()
    yield c
    c.rollback()
    with c.cursor() as cur:
        cur.execute(f"DROP SCHEMA {schema} CASCADE")
    c.commit()
    c.close()


QUERIES = ["lignite outage", "Paris origination pipeline strikes", "reBAP imbalance settlement", "negative prices EEG 51", "Lena notes hedging", "battery VPP"]


def test_same_entitled_documents_as_memory(conn):
    emb = HashEmbedder()
    pg = KnowledgeBase(store=PgVectorStore(conn, emb), embedder=emb)
    mem = KnowledgeBase(store=MemoryStore(emb), embedder=emb)
    for user in org().users:
        for ctx in (Context(user), Context(user, agent="imbalance-risk-check")):
            f = retrieval_filter(ctx)
            ids_pg = {c.doc_id for c, _ in pg.store.vector_search(emb.embed(["x"])[0], f, 100)}
            ids_mem = {c.doc_id for c, _ in mem.store.vector_search(emb.embed(["x"])[0], f, 100)}
            assert ids_pg == ids_mem, (user, ctx)
            for q in QUERIES:
                hits = pg.search(ctx, q)["hits"]
                assert {h["doc_id"] for h in hits} <= ids_mem
    assert pg.stats.filter_cedar_disagreements == 0


def test_chat_documents_are_deleted_on_close(conn):
    emb = HashEmbedder()
    pg = KnowledgeBase(store=PgVectorStore(conn, emb), embedder=emb)
    ctx = Context("marc", chat="pg-chat")
    pg.add_chat_document(ctx, "memo", "the wombat basis is a term only in this chat")
    assert any(h["scope"] == "chat" for h in pg.search(ctx, "wombat basis")["hits"])
    pg.close_chat("pg-chat")
    assert not any(h["scope"] == "chat" for h in pg.search(ctx, "wombat basis")["hits"])

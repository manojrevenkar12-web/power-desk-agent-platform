import json

import cedarpy
import pytest

from powerdesk.kb.corpus import load_corpus
from powerdesk.kb.entitlements import evaluate, retrieval_filter
from powerdesk.policy import Authorizer, Context, _policy_text, _schema
from powerdesk.settings import book, org
from powerdesk.tools.specs import TOOLS

AUTHZ = Authorizer()
BOOKS = set(book().books)


def test_policies_validate_against_the_schema():
    r = cedarpy.validate_policies(_policy_text(), json.dumps(_schema()))
    assert r.validation_passed, r.errors


@pytest.mark.parametrize(
    ("user", "expected"),
    [
        ("lena", {"trading-de", "origination-de", "vpp-de", "vpp-nl"}),
        ("marc", {"trading-fr", "origination-fr"}),
        ("ines", {"origination-fr"}),
        ("ravi", BOOKS),
        ("sofia", set()),
        ("tom", set()),
    ],
)
def test_readable_books(user, expected):
    assert set(AUTHZ.readable_books(Context(user, "desk_agent"))) == expected


@pytest.mark.parametrize("user", sorted(org().users))
def test_developer_tools_never_get_book_tools(user):
    for t in TOOLS:
        d = AUTHZ.tool(Context(user, "developer_tools"), t.name, t.data_class)
        if t.data_class == "book":
            assert not d.allowed
            assert "no-book-data-in-developer-tools" in d.policies or not d.policies


def test_analysts_and_engineers_get_no_book_tools_anywhere():
    for user in ("sofia", "tom"):
        for t in TOOLS:
            if t.data_class == "book":
                assert not AUTHZ.tool(Context(user, "desk_agent"), t.name, t.data_class).allowed


DOCS = {d.id: d for d in load_corpus()}


def test_inside_information_only_for_the_insider_list():
    k7 = DOCS["outage-k7"]
    allowed = {u for u in org().users if AUTHZ.document(Context(u), k7.id, k7.meta).allowed}
    assert allowed == {"lena"}  # ravi reads every confidential document, but is not an insider


def test_confidential_documents_by_desk_and_risk():
    paris = DOCS["paris-pipeline"]
    allowed = {u for u in org().users if AUTHZ.document(Context(u), paris.id, paris.meta).allowed}
    assert allowed == {"marc", "ines", "ravi"}


def test_personal_notes_owner_only():
    notes = DOCS["notes-lena"]
    allowed = {u for u in org().users if AUTHZ.document(Context(u), notes.id, notes.meta).allowed}
    assert allowed == {"lena"}


def test_agent_scope_only_inside_that_skill():
    m = DOCS["method-imbalance"]
    assert not AUTHZ.document(Context("ravi"), m.id, m.meta).allowed
    assert AUTHZ.document(Context("ravi", agent="imbalance-risk-check"), m.id, m.meta).allowed


def _contexts(user):
    yield Context(user)
    yield Context(user, chat="chat-1")
    yield Context(user, agent="imbalance-risk-check")
    yield Context(user, "developer_tools")


def test_retrieval_filter_agrees_with_cedar_everywhere():
    """The Bedrock-style filter and Cedar decide the same for every document, user and context,
    including chat documents in this chat and another chat."""
    metas = [(d.id, d.meta) for d in DOCS.values()]
    base = {"classification": "internal", "desk": "", "owner": "", "agent": "", "insider_list": ""}
    metas += [("chat-a", {**base, "scope": "chat", "chat": "chat-1"}), ("chat-b", {**base, "scope": "chat", "chat": "chat-2"})]
    checked = 0
    for user in org().users:
        for ctx in _contexts(user):
            f = retrieval_filter(ctx)
            for doc_id, meta in metas:
                meta = {"chat": "", **meta}
                assert evaluate(f, meta) == AUTHZ.document(ctx, doc_id, meta).allowed, (user, ctx, doc_id)
                checked += 1
    assert checked == 6 * 4 * (len(DOCS) + 2)

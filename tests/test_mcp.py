"""The MCP server over streamable HTTP, as Claude Code or any MCP client would call it."""

import json

import pytest
from starlette.testclient import TestClient

from powerdesk.auth import mint_dev_token
from powerdesk.mcp_server import asgi_app

H = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json", "MCP-Protocol-Version": "2025-11-25"}
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}}


@pytest.fixture(scope="module")
def client(gateway):
    with TestClient(asgi_app(gateway)) as c:
        yield c


def rpc(c, path, user, method, params=None):
    h = {**H, "Authorization": f"Bearer {mint_dev_token(user)}"} if user else H
    c.post(path, json=INIT, headers=h)
    return c.post(path, json={"jsonrpc": "2.0", "id": 2, "method": method, **({"params": params} if params else {})}, headers=h)


def names(r):
    return {t["name"] for t in r.json()["result"]["tools"]}


def test_no_token_no_tools(client):
    r = rpc(client, "/desk/mcp", None, "tools/list")
    assert r.status_code == 401 and "resource_metadata" in r.headers["www-authenticate"]


def test_tools_are_listed_per_user_and_surface(client):
    assert len(names(rpc(client, "/desk/mcp", "lena", "tools/list"))) == 12
    assert "ppa_valuation" not in names(rpc(client, "/desk/mcp", "sofia", "tools/list"))
    dev = names(rpc(client, "/dev/mcp", "ravi", "tools/list"))
    assert dev == {"price_stats", "negative_prices", "capture_price", "price_drivers", "forecast_error", "search_knowledge"}


def test_call_returns_the_tool_result(client):
    r = rpc(client, "/desk/mcp", "lena", "tools/call", {"name": "price_stats", "arguments": {"zone": "DE-LU", "start": "2026-07-01", "end": "2026-08-01"}})
    body = json.loads(r.json()["result"]["content"][0]["text"])
    assert body["average"] == 83.03 and body["units"]["average"] == "EUR/MWh"


def test_policy_denial_is_a_tool_error(client):
    r = rpc(client, "/desk/mcp", "marc", "tools/call", {"name": "ppa_valuation", "arguments": {"ppa": "PPA-DE-SOL-01", "start": "2026-07-01", "end": "2026-08-01"}})
    res = r.json()["result"]
    assert res["isError"] and "not permitted" in res["content"][0]["text"]


def test_book_tool_does_not_exist_on_the_developer_surface(client):
    r = rpc(client, "/dev/mcp", "ravi", "tools/call", {"name": "ppa_portfolio", "arguments": {"books": ["trading-de"], "start": "2026-07-01", "end": "2026-08-01"}})
    assert r.json()["result"]["isError"]


def test_dns_rebinding_is_refused(client):
    r = client.post("/desk/mcp", json=INIT, headers={**H, "Host": "evil.example", "Authorization": f"Bearer {mint_dev_token('lena')}"})
    assert r.status_code == 421

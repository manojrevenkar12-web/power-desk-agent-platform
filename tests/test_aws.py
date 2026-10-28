from types import SimpleNamespace

from fastapi.testclient import TestClient

from powerdesk.auth import ENVELOPE_KEY, mint_dev_token, seal
from powerdesk.aws import interceptors, tool_lambda
from powerdesk.aws.runtime_app import create_app

ARGS = {"ppa": "PPA-DE-SOL-01", "start": "2026-07-01", "end": "2026-08-01"}
CTX = SimpleNamespace(client_context=SimpleNamespace(custom={"bedrockAgentCoreToolName": "desk___ppa_valuation", "bedrockAgentCoreGatewayId": "gw-1"}))


def call_event(user, arguments, method="tools/call"):
    return {
        "interceptorInputVersion": "1.0",
        "mcp": {
            "gatewayRequest": {
                "path": "/mcp",
                "httpMethod": "POST",
                "headers": {"Authorization": f"Bearer {mint_dev_token(user)}"},
                "body": {"jsonrpc": "2.0", "id": 7, "method": method, "params": {"name": "desk___ppa_valuation", "arguments": arguments}},
            }
        },
    }


def test_interceptor_replaces_a_forged_identity(gateway):
    out = interceptors.request_handler(call_event("lena", {**ARGS, ENVELOPE_KEY: seal("ravi", "desk_agent")[:-4] + "AAAA"}))
    args = out["mcp"]["transformedGatewayRequest"]["body"]["params"]["arguments"]
    assert "authorization" not in {k.lower() for k in out["mcp"]["transformedGatewayRequest"]["headers"]}
    r = tool_lambda.handler(dict(args), CTX, gateway=gateway)
    assert r["book"] == "origination-de"


def test_interceptor_rejects_a_bad_token():
    ev = call_event("lena", ARGS)
    ev["mcp"]["gatewayRequest"]["headers"]["Authorization"] = "Bearer nonsense"
    out = interceptors.request_handler(ev)
    assert out["mcp"]["transformedGatewayResponse"]["body"]["error"]["code"] == -32001


def test_lambda_refuses_calls_without_the_envelope(gateway):
    assert "no caller identity" in tool_lambda.handler(dict(ARGS), CTX, gateway=gateway)["error"]


def test_lambda_applies_cedar_for_the_sealed_user(gateway):
    r = tool_lambda.handler({**ARGS, ENVELOPE_KEY: seal("marc", "desk_agent")}, CTX, gateway=gateway)
    assert r["error"].startswith("not permitted") and r["denied_by"]


def test_lambda_on_the_developer_surface_refuses_book_tools(gateway):
    r = tool_lambda.handler({**ARGS, ENVELOPE_KEY: seal("ravi", "developer_tools")}, CTX, gateway=gateway)
    assert "not permitted" in r["error"]


def test_response_interceptor_filters_tools_list(monkeypatch):
    monkeypatch.setenv("POWERDESK_SURFACE", "desk_agent")
    ev = {
        "mcp": {
            "gatewayRequest": {"headers": {"Authorization": f"Bearer {mint_dev_token('tom')}"}, "body": {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}},
            "gatewayResponse": {"statusCode": 200, "body": {"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "desk___price_stats"}, {"name": "desk___hedge_report"}]}}},
        }
    }
    tools = interceptors.response_handler(ev)["mcp"]["transformedGatewayResponse"]["body"]["result"]["tools"]
    assert [t["name"] for t in tools] == ["desk___price_stats"]


def test_runtime_container_contract(desk):
    c = TestClient(create_app(desk))
    assert c.get("/ping").json() == {"status": "Healthy"}
    assert c.post("/invocations", json={"prompt": "hi"}).status_code == 401
    r = c.post("/invocations", json={"prompt": "Average day-ahead price in FR in August 2026?"}, headers={"Authorization": f"Bearer {mint_dev_token('marc')}"})
    body = r.json()
    assert r.status_code == 200 and body["tool_calls"][0]["name"] == "price_stats" and body["answer"]
    s = c.post("/invocations", json={"prompt": "Average day-ahead price in FR in August 2026?"}, headers={"Authorization": f"Bearer {mint_dev_token('marc')}", "Accept": "text/event-stream"})
    assert "event: answer" in s.text and "event: tool_call" in s.text

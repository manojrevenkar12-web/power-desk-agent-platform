"""AgentCore Gateway interceptors (Lambda, interceptorInputVersion 1.0).

REQUEST interceptor, on every MCP request (configure `passRequestHeaders: true` so it receives the
Authorization header):
- verifies the caller's token (the gateway's own JWT authorizer checked it too; this one needs the
  desk user from it);
- for `tools/call`, removes any `_desk_identity` argument the client sent and adds one signed with
  the key shared only with the tool Lambda;
- answers with a JSON-RPC error, without calling the target, when the token names no desk user.

RESPONSE interceptor, for `tools/list`: removes the tools Cedar would refuse for this user on this
gateway's surface, so a model never sees a tool it may not use. (AgentCore Policy does the same
with Cedar in the managed service; this keeps it identical locally and in tests.)

The surface comes from the gateway (one gateway per surface: `POWERDESK_SURFACE`), never from the client.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

from powerdesk.auth import ENVELOPE_KEY, Unauthorized, seal, verify
from powerdesk.policy import Authorizer, Context
from powerdesk.tools.gateway import ToolGateway

DELIMITER = "___"


def _surface() -> str:
    s = os.environ.get("POWERDESK_SURFACE", "desk_agent")
    if s not in ("desk_agent", "developer_tools"):
        raise ValueError(f"bad POWERDESK_SURFACE {s}")
    return s


@lru_cache
def _gateway() -> ToolGateway:
    return ToolGateway(Authorizer())


def _bearer(headers: dict[str, Any] | None) -> str:
    for k, v in (headers or {}).items():
        if k.lower() == "authorization" and str(v).lower().startswith("bearer "):
            return str(v)[7:].strip()
    return ""


def _body(x: Any) -> dict[str, Any]:
    if isinstance(x, str):
        return json.loads(x) if x else {}
    return dict(x or {})


def _reject(rpc_id: Any, message: str) -> dict[str, Any]:
    return {
        "interceptorOutputVersion": "1.0",
        "mcp": {"transformedGatewayResponse": {"statusCode": 200, "body": {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32001, "message": message}}}},
    }


def request_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    req = event["mcp"]["gatewayRequest"]
    body = _body(req.get("body"))
    method = body.get("method", "")
    headers = req.get("headers") or {}
    out_headers = {k: v for k, v in headers.items() if k.lower() != "authorization"}
    if method in ("initialize", "notifications/initialized", "ping"):
        return {"interceptorOutputVersion": "1.0", "mcp": {"transformedGatewayRequest": {"headers": out_headers, "body": body}}}
    try:
        user = verify(_bearer(headers)).user
    except Unauthorized as e:
        return _reject(body.get("id"), f"unauthorised: {e}")
    if method == "tools/call":
        params = dict(body.get("params") or {})
        args = {k: v for k, v in dict(params.get("arguments") or {}).items() if k != ENVELOPE_KEY}
        args[ENVELOPE_KEY] = seal(user, _surface())
        params["arguments"] = args
        body = {**body, "params": params}
    return {"interceptorOutputVersion": "1.0", "mcp": {"transformedGatewayRequest": {"headers": out_headers, "body": body}}}


def response_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    mcp = event["mcp"]
    req_body = _body((mcp.get("gatewayRequest") or {}).get("body"))
    resp = mcp.get("gatewayResponse") or {}
    resp_body = _body(resp.get("body"))
    status = int(resp.get("statusCode", 200))
    if req_body.get("method") == "tools/list" and "result" in resp_body:
        try:
            user = verify(_bearer((mcp.get("gatewayRequest") or {}).get("headers"))).user
            allowed = {t.name for t in _gateway().list_tools(Context(user, _surface()))}  # type: ignore[arg-type]
        except Unauthorized:
            allowed = set()
        tools = [t for t in resp_body["result"].get("tools", []) if str(t.get("name", "")).split(DELIMITER)[-1] in allowed]
        resp_body = {**resp_body, "result": {**resp_body["result"], "tools": tools}}
    return {"interceptorOutputVersion": "1.0", "mcp": {"transformedGatewayResponse": {"statusCode": status, "body": resp_body}}}

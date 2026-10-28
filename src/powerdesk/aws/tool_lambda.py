"""One Lambda for all desk tools, registered as an AgentCore Gateway Lambda target.

AgentCore Gateway calls it with the tool's arguments as `event` and the tool name in
`context.client_context.custom["bedrockAgentCoreToolName"]` (`<target>___<tool>`). The caller's
identity is not in that context, so the REQUEST interceptor adds a signed `_desk_identity`
argument after verifying the user's token; this Lambda refuses calls without a valid one. A model
cannot forge it: the interceptor strips any `_desk_identity` the client sent.

The same ToolGateway runs here as in the agent and the MCP server, so Cedar decides the same way
whichever door a call comes through.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

from powerdesk.auth import ENVELOPE_KEY, Unauthorized, unseal
from powerdesk.policy import Context
from powerdesk.tools.gateway import ToolGateway

log = logging.getLogger("powerdesk.tool_lambda")
log.setLevel(logging.INFO)
DELIMITER = "___"


@lru_cache
def _gateway() -> ToolGateway:
    from powerdesk.desk import build_desk

    return build_desk().gateway


def tool_name(context: Any) -> str:
    custom = getattr(getattr(context, "client_context", None), "custom", None) or {}
    full = str(custom.get("bedrockAgentCoreToolName", ""))
    if not full:
        raise ValueError("no bedrockAgentCoreToolName in the client context")
    return full.split(DELIMITER, 1)[1] if DELIMITER in full else full


def handler(event: dict[str, Any], context: Any, gateway: ToolGateway | None = None) -> dict[str, Any]:
    args = dict(event or {})
    envelope = args.pop(ENVELOPE_KEY, None)
    try:
        name = tool_name(context)
    except ValueError as e:
        return {"error": str(e)}
    if not isinstance(envelope, str):
        return {"error": "no caller identity; calls must come through the desk gateway"}
    try:
        user, surface = unseal(envelope)
    except Unauthorized as e:
        return {"error": f"caller identity rejected: {e}"}
    gw = gateway or _gateway()
    o = gw.call(Context(user, surface), name, args)  # type: ignore[arg-type]
    # log the decision, never the arguments or results (book data stays out of CloudWatch)
    log.info(json.dumps({"tool": name, "user": user, "surface": surface, "ok": o.ok, "denied_by": list(o.denied_by), "call_id": o.call_id}))
    return o.as_content()

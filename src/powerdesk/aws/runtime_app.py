"""The desk agent as an Amazon Bedrock AgentCore Runtime container: `POST /invocations` and
`GET /ping` on port 8080 (arm64 image). Inbound auth is the runtime's JWT authorizer; the
container verifies the same token again (the runtime passes `Authorization` when it is on the
request header allowlist) because the desk user comes from it.

Request: {"prompt": "...", "chat": "optional chat id"}. Response: the answer, the tool calls
(name, ok, policy denials) and the grounding report. With `Accept: text/event-stream` the agent's
events stream as they happen.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from powerdesk.auth import Unauthorized, verify
from powerdesk.desk import Desk, build_desk
from powerdesk.policy import Context


class Invocation(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    chat: str = Field(default="", max_length=64, pattern=r"^[A-Za-z0-9_-]*$")


def create_app(desk: Desk | None = None) -> FastAPI:
    app = FastAPI(title="power-desk agent runtime", docs_url=None, redoc_url=None)
    state: dict[str, Desk] = {}

    def get_desk() -> Desk:
        if "desk" not in state:
            state["desk"] = desk or build_desk()
        return state["desk"]

    def user_of(authorization: str | None) -> str:
        token = (authorization or "").removeprefix("Bearer ").strip()
        try:
            return verify(token).user
        except Unauthorized as e:
            raise HTTPException(401, f"unauthorised: {e}") from e

    @app.get("/ping")
    def ping() -> dict[str, str]:
        return {"status": "Healthy"}

    @app.post("/invocations", response_model=None)
    def invocations(body: Invocation, authorization: str | None = Header(default=None), accept: str | None = Header(default=None)) -> Any:
        ctx = Context(user_of(authorization), "desk_agent", chat=body.chat)
        d = get_desk()
        if accept and "text/event-stream" in accept:

            def events() -> Iterator[str]:
                for ev in d.agent.stream(ctx, body.prompt):
                    data = ev.data if ev.kind != "tool_result" else {"name": ev.data["name"], "status": ev.data["status"]}
                    yield f"event: {ev.kind}\ndata: {json.dumps(data, default=str)}\n\n"

            return StreamingResponse(events(), media_type="text/event-stream")
        turn = d.agent.ask(ctx, body.prompt)
        return {
            "answer": turn.answer,
            "skill": turn.skill,
            "redacted": turn.redacted,
            "corrections": turn.corrections,
            "tool_calls": [{"name": t["name"], "ok": t["ok"], "call_id": t["call_id"], "denied_by": t["denied_by"]} for t in turn.tool_calls],
            "verification": turn.verification,
            "usage": turn.usage,
        }

    return app


app = create_app()

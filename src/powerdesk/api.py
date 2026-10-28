"""HTTP API for the desk console. Same agent, gateway and policies as every other door.

Auth: `Authorization: Bearer <token>` (OIDC in AWS, dev tokens locally). The dev sign-in route
exists only outside production and only mints tokens for the fictional desk users.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from powerdesk.auth import Unauthorized, mint_dev_token, verify
from powerdesk.desk import Desk, build_desk
from powerdesk.policy import Context
from powerdesk.settings import ROOT, org

PROD = os.environ.get("POWERDESK_ENV", "dev") == "prod"


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    surface: str = Field(default="desk_agent", pattern=r"^(desk_agent|developer_tools)$")
    attach_title: str = Field(default="", max_length=120)
    attach_text: str = Field(default="", max_length=20_000)


class DevLogin(BaseModel):
    user: str


def _read(rel: str) -> Any | None:
    p = ROOT / rel
    return json.loads(p.read_text()) if p.exists() else None


def create_app(desk: Desk | None = None) -> FastAPI:
    app = FastAPI(title="power-desk API", docs_url=None if PROD else "/api/docs", openapi_url=None if PROD else "/api/openapi.json")
    state: dict[str, Desk] = {}
    chats = {"n": 0}

    def get_desk() -> Desk:
        if "d" not in state:
            state["d"] = desk or build_desk()
        return state["d"]

    def user(authorization: str | None = Header(default=None)) -> str:
        try:
            return verify((authorization or "").removeprefix("Bearer ").strip()).user
        except Unauthorized as e:
            raise HTTPException(401, "sign in first") from e

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/users")
    def users() -> list[dict[str, Any]]:
        if PROD:
            raise HTTPException(404)
        return [{"id": k, "name": u.name, "role": u.role, "desk": u.desk} for k, u in org().users.items()]

    @app.post("/api/dev/login")
    def dev_login(body: DevLogin) -> dict[str, str]:
        if PROD:
            raise HTTPException(404)
        if body.user not in org().users:
            raise HTTPException(400, "unknown user")
        return {"token": mint_dev_token(body.user, 240)}

    @app.get("/api/me")
    def me(u: str = Depends(user)) -> dict[str, Any]:
        d = get_desk()
        info = org().users[u]
        ctx = Context(u, "desk_agent")
        return {
            "id": u,
            "name": info.name,
            "role": info.role,
            "desk": info.desk,
            "books": d.authz.readable_books(ctx),
            "tools": {s: [t.name for t in d.gateway.list_tools(Context(u, s))] for s in ("desk_agent", "developer_tools")},  # type: ignore[arg-type]
            "skills": sorted(d.agent.skills),
        }

    @app.post("/api/ask")
    def ask(body: AskBody, u: str = Depends(user)) -> dict[str, Any]:
        d = get_desk()
        chat = ""
        if body.attach_text:
            chats["n"] += 1
            chat = f"console-{chats['n']}"
        ctx = Context(u, body.surface, chat=chat)  # type: ignore[arg-type]
        if chat:
            d.kb.add_chat_document(ctx, body.attach_title or "Attachment", body.attach_text)
        try:
            turn = d.agent.ask(ctx, body.question)
        finally:
            if chat:
                d.kb.close_chat(chat)
        return {
            "question": turn.question,
            "answer": turn.answer,
            "skill": turn.skill,
            "redacted": turn.redacted,
            "corrections": turn.corrections,
            "model_calls": turn.model_calls,
            "ms": round(turn.ms, 1),
            "numbers": turn.verification,
            "tool_calls": [{k: t[k] for k in ("name", "input", "ok", "call_id", "denied_by", "error", "result")} for t in turn.tool_calls],
        }

    @app.get("/api/market/day")
    def market_day(zone: str = "DE-LU", day: str = "2026-08-12", u: str = Depends(user)) -> dict[str, Any]:
        """One delivery day in 15-minute products (market data: every desk user may read it)."""
        from datetime import date, timedelta

        from powerdesk.quant.common import Period, QuantError, local_str, window

        try:
            d = date.fromisoformat(day)
            w = window(zone, Period.parse(d.isoformat(), (d + timedelta(days=1)).isoformat()))
        except (ValueError, QuantError) as e:
            raise HTTPException(400, str(e)) from e
        return {
            "zone": zone,
            "day": day,
            "intervals": [
                {"at": local_str(ts), "da": round(float(r.da_price), 2), "solar_mw": round(float(r.solar_mw)), "wind_mw": round(float(r.wind_onshore_mw + r.wind_offshore_mw))}
                for ts, r in w.iterrows()
            ],
        }

    @app.get("/api/evals")
    def evals(u: str = Depends(user)) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for n in ("dev", "redteam", "ablation"):
            r = _read(f"reports/evals/{n}.json")
            if r:
                out[n] = {"summary": r["summary"], "cases_sha256": r.get("cases_sha256"), "cases": [{"id": c["id"], "user": c["user"], "passed": c["passed"]} for c in r["cases"]]}
        hd = ROOT / "reports" / "heldout"
        out["heldout"] = {}
        for p in sorted(hd.glob("*/first_run.json")) if hd.exists() else []:
            r = json.loads(p.read_text())
            out["heldout"][p.parent.name] = {"summary": r["summary"], "cases_sha256": r["cases_sha256"], "recorded_at": r.get("recorded_at"), "status": r.get("status")}
        return out

    @app.get("/api/connectors")
    def connectors(u: str = Depends(user)) -> dict[str, Any]:
        r = _read("reports/connectors/fitness.json")
        if r is None:
            raise HTTPException(404, "no connector report yet: run `powerdesk connectors`")
        return r

    @app.get("/api/rollout")
    def rollout(u: str = Depends(user)) -> dict[str, Any]:
        from powerdesk.rollout import build, validate
        from powerdesk.settings import read_yaml

        cfg = read_yaml("config/rollout.yaml")
        teams = {}
        for t, info in cfg["teams"].items():
            s, m = build(t, cfg)
            teams[t] = {"description": info["description"], "managed_settings": s, "managed_mcp": m, "problems": validate(s, m)}
        return {"paths": cfg["paths"], "teams": teams}

    @app.get("/api/audit")
    def audit(u: str = Depends(user)) -> list[dict[str, Any]]:
        role = org().users[u].role
        rows = get_desk().gateway.calls.entries
        return [r for r in rows if role == "risk" or r["user"] == u][-200:]

    dist = Path(os.environ.get("POWERDESK_CONSOLE_DIST", ROOT / "console" / "dist"))
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            f = dist / path
            return FileResponse(f if path and f.is_file() else dist / "index.html")

    return app


app = create_app()

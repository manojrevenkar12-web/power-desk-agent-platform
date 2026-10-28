"""The desk's tools as MCP servers (streamable HTTP, stateless, MCP 2026-07-28 with fallback).

Two endpoints, one per surface, because the surface decides policy and must not be something a
client can claim:

- `/desk/mcp`: for desk agents and chat clients.
- `/dev/mcp`: for developer tools (Claude Code, Copilot). Cedar forbids book tools here, so they
  are not even listed.

Every call goes through the same ToolGateway as the agent. Tools/list is filtered per user and
carries a cache hint, so clients do not refetch it on every turn.
"""

from __future__ import annotations

import inspect
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, cast

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.caching import CacheHint
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl, Field
from starlette.applications import Starlette
from starlette.routing import Mount

from powerdesk.auth import Unauthorized, verify
from powerdesk.policy import Context, Surface
from powerdesk.tools.gateway import ToolGateway
from powerdesk.tools.specs import TOOLS, ToolSpec


class DeskTokenVerifier:
    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            p = verify(token)
        except Unauthorized:
            return None
        return AccessToken(token=token, client_id=p.user, scopes=["desk"], subject=p.user, claims={"desk_user": p.user})


def _user() -> str:
    tok = get_access_token()
    if tok is None or not tok.claims:
        raise ToolError("not signed in")
    return str(tok.claims["desk_user"])


def _signature(spec: ToolSpec) -> inspect.Signature:
    params = []
    for name, f in spec.args.model_fields.items():
        meta = [*f.metadata, Field(description=f.description)] if f.description else list(f.metadata)
        ann = Annotated[(f.annotation, *meta)] if meta else f.annotation
        default = inspect.Parameter.empty if f.is_required() else f.default
        params.append(inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=ann, default=default))
    return inspect.Signature(params, return_annotation=str)


class DeskMCPServer(MCPServer[Any]):
    """tools/list shows only what Cedar lets the signed-in user invoke from this surface."""

    def __init__(self, gateway: ToolGateway, surface: Surface, **kw: Any) -> None:
        super().__init__(**kw)
        self.gateway = gateway
        self.surface = surface

    async def list_tools(self) -> list[Any]:
        tools = await super().list_tools()
        tok = get_access_token()
        if tok is None or not tok.claims:
            return []
        allowed = {t.name for t in self.gateway.list_tools(Context(str(tok.claims["desk_user"]), self.surface))}
        return [t for t in tools if t.name in allowed]


def build_server(gateway: ToolGateway, surface: Surface, public_url: str) -> DeskMCPServer:
    srv = DeskMCPServer(
        gateway,
        surface,
        name=f"power-desk-{surface.replace('_', '-')}",
        instructions="Market data, desk knowledge and (for desk agents) book analytics of a European power trading desk. Numbers in results are authoritative; state them as returned.",
        auth=AuthSettings(issuer_url=AnyHttpUrl(os.environ.get("POWERDESK_OIDC_ISSUER", "https://powerdesk.invalid/dev")), resource_server_url=AnyHttpUrl(public_url), validate_token_resource=False),
        token_verifier=DeskTokenVerifier(),
        cache_hints={"tools/list": CacheHint(ttl_ms=300_000, scope="private")},
    )
    for spec in TOOLS:

        def make(spec: ToolSpec = spec) -> Any:
            def fn(**kwargs: Any) -> str:
                ctx = Context(_user(), surface)
                o = gateway.call(ctx, spec.name, {k: v for k, v in kwargs.items() if v is not None or k in spec.args.model_fields})
                if not o.ok:
                    raise ToolError(o.error or "refused")
                return json.dumps(o.as_content(), default=str)

            fn.__signature__ = _signature(spec)  # type: ignore[attr-defined]
            fn.__name__ = spec.name
            return fn

        # developer tools never see book tools listed (Cedar would refuse them anyway)
        if surface == "developer_tools" and spec.data_class == "book":
            continue
        srv.add_tool(make(), name=spec.name, description=spec.description)
    return srv


def allowed_hosts() -> list[str]:
    return [h.strip() for h in os.environ.get("POWERDESK_ALLOWED_HOSTS", "localhost:*,127.0.0.1:*,testserver").split(",") if h.strip()]


def asgi_app(gateway: ToolGateway, public_url: str = "http://localhost:8000") -> Starlette:
    """Both surfaces in one process: `/desk/mcp` and `/dev/mcp`, stateless streamable HTTP."""
    security = TransportSecuritySettings(allowed_hosts=allowed_hosts(), allowed_origins=[])
    apps = {
        name: build_server(gateway, surface, f"{public_url}/{name}/mcp").streamable_http_app(stateless_http=True, json_response=True, transport_security=security)
        for name, surface in (("desk", cast(Surface, "desk_agent")), ("dev", cast(Surface, "developer_tools")))
    }

    @asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        async with apps["desk"].router.lifespan_context(apps["desk"]), apps["dev"].router.lifespan_context(apps["dev"]):
            yield

    return Starlette(routes=[Mount(f"/{n}", app=a) for n, a in apps.items()], lifespan=lifespan)

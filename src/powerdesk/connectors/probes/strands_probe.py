import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import ARGS, DEV_URL, HEADERS, URL, run, text_of


async def go() -> dict:
    try:
        from mcp.client.streamable_http import streamablehttp_client as client
    except ImportError:  # renamed in mcp 2.x
        from mcp.client.streamable_http import streamable_http_client as client

    import inspect

    def transport(url, headers=None):
        if "headers" in inspect.signature(client).parameters:
            return client(url, headers=headers)
        import httpx2  # mcp 2.x takes a configured client instead of headers

        return client(url, http_client=httpx2.AsyncClient(headers=headers or {}))

    from strands.tools.mcp import MCPClient

    def names(c) -> list[str]:
        return sorted(t.tool_name for t in c.list_tools_sync())

    with MCPClient(lambda: transport(URL, HEADERS)) as c:
        tools = names(c)
        res = c.call_tool_sync("probe-1", "price_stats", ARGS)
    with MCPClient(lambda: transport(DEV_URL, HEADERS)) as c:
        dev_tools = names(c)
    try:
        with MCPClient(lambda: transport(URL)) as c:
            names(c)
        anon = "listed tools without a token"
    except BaseException as e:
        anon = f"refused: {type(e).__name__}"
    return {"tools": tools, "dev_tools": dev_tools, "call_text": text_of(res.get("content") if isinstance(res, dict) else res), "anonymous": anon}


run("import strands, strands.tools.mcp", go)

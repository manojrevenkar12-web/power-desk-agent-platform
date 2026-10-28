import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import ARGS, DEV_URL, HEADERS, URL, run, text_of


async def go() -> dict:
    from langchain_mcp_adapters.client import MultiServerMCPClient

    desk = MultiServerMCPClient({"desk": {"transport": "streamable_http", "url": URL, "headers": HEADERS}})
    tools = await desk.get_tools()
    price = next(t for t in tools if t.name == "price_stats")
    res = await price.ainvoke(ARGS)
    dev = MultiServerMCPClient({"dev": {"transport": "streamable_http", "url": DEV_URL, "headers": HEADERS}})
    dev_tools = await dev.get_tools()
    try:
        await MultiServerMCPClient({"x": {"transport": "streamable_http", "url": URL}}).get_tools()
        anon = "listed tools without a token"
    except Exception as e:
        anon = f"refused: {type(e).__name__}"
    return {"tools": sorted(t.name for t in tools), "dev_tools": sorted(t.name for t in dev_tools), "call_text": text_of(res), "anonymous": anon}


run("import langchain_core, langchain_mcp_adapters.client, langchain_aws", go)

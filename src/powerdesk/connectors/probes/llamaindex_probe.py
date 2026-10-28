import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import ARGS, DEV_URL, HEADERS, URL, run, text_of


async def go() -> dict:
    from llama_index.tools.mcp import BasicMCPClient, McpToolSpec

    tools = await McpToolSpec(client=BasicMCPClient(URL, headers=HEADERS)).to_tool_list_async()
    price = next(t for t in tools if t.metadata.name == "price_stats")
    res = await price.acall(**ARGS)
    dev_tools = await McpToolSpec(client=BasicMCPClient(DEV_URL, headers=HEADERS)).to_tool_list_async()
    try:
        await McpToolSpec(client=BasicMCPClient(URL)).to_tool_list_async()
        anon = "listed tools without a token"
    except BaseException as e:
        anon = f"refused: {type(e).__name__}"
    return {"tools": sorted(t.metadata.name for t in tools), "dev_tools": sorted(t.metadata.name for t in dev_tools), "call_text": text_of(res), "anonymous": anon}


run("import llama_index.core, llama_index.tools.mcp, llama_index.llms.bedrock_converse", go)

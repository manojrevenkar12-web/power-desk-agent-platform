# 5. No agent framework in the shipping path; frameworks are measured against it

**Status:** accepted

**Context.** The team has to decide on LangChain, LlamaIndex and n8n for a regulated environment where IP is sensitive. The questions that decide this are concrete:
- what each one installs, and under which licences;
- what it does on the network;
- whether it fits a Lambda;
- whether it respects the desk's entitlements.

**Decision.**
- The shipping path uses the Bedrock Converse API directly, with MCP for tools.
- `powerdesk connectors` installs each Python framework into a clean environment.
- It blocks and records every connection the framework makes other than to the desk server.
- It loads the desk's MCP tools with a user's token and checks that the returned value equals the gateway's own.
- n8n is a Node.js application, so it is assessed from its documentation.

**Consequences.**
- `docs/CONNECTORS.md` is generated, not written. All three Python frameworks pass the bar as measured.
- Entitlements hold whichever framework a team picks, because they sit behind MCP.
- Re-run the harness whenever a version changes.

# 1. One tool gateway for every door

**Status:** accepted

**Context.** Desk tools are reached in three ways:
- by the desk agent (Bedrock Converse);
- by developer tools over MCP (Claude Code, Copilot);
- by AgentCore Gateway through a Lambda target.

If each door checked access its own way, they would drift apart, and the weakest door would decide what leaks.

**Decision.** Every call goes through `ToolGateway.call`, which runs the same checks in the same order:
1. The tool exists.
2. Cedar allows this principal to invoke it from this surface.
3. The arguments validate.
4. Cedar allows reading every book the call touches.
5. Only then does the tool run.

The surface (desk agent or developer tools) comes from the endpoint or the gateway, never from the client. Policies live in `policies/desk.cedar` and are validated against `policies/schema.json`.

**Consequences.**
- Tests run the same policies through every door: `tests/test_mcp.py`, `tests/test_aws.py` and `tests/test_api.py`.
- AgentCore Policy, which applies Cedar at the managed gateway, can be added as a second line. The book-level decisions stay here, because they depend on the tool's arguments and on the desk's book configuration.

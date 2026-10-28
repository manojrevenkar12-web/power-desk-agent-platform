# 6. Claude Code through Bedrock, with endpoint-managed settings

**Status:** accepted

**Context.** The desk wants Claude Code without code or prompts leaving the firm's AWS boundary. Claude Code does not fetch server-managed settings when a third-party provider such as Bedrock is selected.

**Decision.** Settings are endpoint-managed. `powerdesk rollout` generates `managed-settings.json` and `managed-mcp.json` for each team from `config/rollout.yaml`, and they are deployed with MDM. The settings:
- use Bedrock in the EU;
- turn off telemetry and nonessential traffic;
- accept permission rules only from managed settings, and disable bypass mode;
- deny reads of secrets and book exports;
- allow exactly one MCP server: the desk's developer-tools surface, which carries no book tools.

The settings are validated against the documented rules before they are written.

**Consequences.**
- A bad edit fails in CI, not on a laptop.
- Copilot is covered separately, in `docs/ROLLOUT.md`: content exclusion does not cover its agent modes, so the guidance there differs.

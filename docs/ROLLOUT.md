# Rolling out Claude Code and Copilot to the desk

## Claude Code, through Amazon Bedrock

`powerdesk rollout` writes two files per team into `rollout/out/<team>/`, from `config/rollout.yaml`:

- `managed-settings.json`;
- `managed-mcp.json`.

Deploy both with MDM to:

| OS | Path |
|---|---|
| Linux | `/etc/claude-code/` |
| macOS | `/Library/Application Support/ClaudeCode/` |
| Windows | `C:\Program Files\ClaudeCode\` |

Every team gets these settings:

- **Model access through Bedrock in the EU.** `CLAUDE_CODE_USE_BEDROCK=1`, `AWS_REGION=eu-central-1` and an `eu.` inference profile. Code and prompts stay in the firm's AWS account. Claude Code skips the server-managed settings fetch when a third-party provider is selected, so on Bedrock the policy has to arrive as these files.
- **No telemetry.** `DISABLE_TELEMETRY`, `DISABLE_ERROR_REPORTING` and `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` are all set to `1`.
- **Permissions only from these files.**
  - `allowManagedPermissionRulesOnly: true`.
  - `disableBypassPermissionsMode: "disable"`.
  - Deny rules for secrets, keys and position or book exports, and for `curl`, `wget` and `aws s3 cp/sync`.
  - `git push` needs confirmation.
- **One MCP server.**
  - `allowManagedMcpServersOnly: true`, and `allowedMcpServers` names only the desk's developer-tools endpoint.
  - That endpoint lists no book tools, and Cedar would refuse them anyway.
  - The server authenticates with OAuth through the identity provider, using the protected-resource metadata it serves, so no token sits in a file.

Team differences: technology may search the web and run tests. Front office may neither fetch nor search the web.

`rollout.validate` checks the documented rules before anything is written:

- every MCP server is HTTPS;
- no `${VAR}` expansion;
- no `command`, `args`, `env` or `headersHelper` on managed servers;
- no static `Authorization` header;
- every rule is a tool rule;
- no rule is both allowed and denied;
- the region is in the EU.

`tests/test_rollout.py` breaks each rule once and checks that the validator catches it. Before a wider rollout, check on a test machine with `claude doctor` and `/permissions`.

## GitHub Copilot

- **Content exclusion.** Set it at organisation level for the same paths: `.env*`, `secrets/`, `*.pem`, `*.key`, `**/positions/**` and `**/books/**`. GitHub documents that content exclusion is **not** applied in Copilot Chat's Edit and Agent modes in VS Code and other editors. Teams that handle book data should therefore turn those modes off by policy, or work in repositories that hold no such data. ([GitHub docs](https://docs.github.com/en/copilot/concepts/context/content-exclusion))
- **MCP.** Allow only the desk's developer-tools endpoint, with the organisation's MCP server policy. Its tools are the same Cedar-checked market and knowledge tools that Claude Code gets.
- **Models.** Restrict models to those the firm has approved in the Copilot policy settings.

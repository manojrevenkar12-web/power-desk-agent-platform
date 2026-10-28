# Working on power-desk-agent-platform

## Fast feedback

- `scripts/check.sh` runs in under a minute: ruff, mypy, the tests without database or synth, the eval suites and the release gate.
- `pytest -q` runs everything:
  - the pgvector tests need `POWERDESK_TEST_DATABASE_URL`, pointing at Postgres with pgvector;
  - the CDK synth with cdk-nag needs Node.
- `cd console && npm test && npx playwright test` runs the UI unit tests, then end-to-end against the real API.
- `powerdesk connectors` measures the frameworks (minutes; needs `uv` and package registry access).

## Invariants (each has a test)

- **One gateway.** Every tool call, from the agent, MCP, AgentCore Lambda or the API, goes through `ToolGateway.call`. Access is decided in `policies/*.cedar`, never in a prompt and never in a tool. (`tests/test_policy.py`, `test_mcp.py`, `test_aws.py`)
- **Surface comes from the door.** The surface (`desk_agent` or `developer_tools`) comes from the endpoint or the gateway, never from the client. Developer tools never get book tools.
- **Filter and Cedar agree.** The retrieval filter and Cedar agree for every document, user and context. Hits are re-checked with Cedar. (`test_policy.py::test_retrieval_filter_agrees_with_cedar_everywhere`)
- **Numbers are traced.** No untraced number reaches a user while grounding is on. (`test_agent.py`, the gate)
- **The simulated model sees only the request.** `agent/sim.py` imports nothing from the platform. (`test_agent.py`)
- **The reference is independent.** `evals/reference.py` imports nothing from `quant` or `tools`. (`test_quant.py`)
- **Settings live in config.** Thresholds, users, books, rollout rules and infrastructure settings live in `config/`, not in code.
- **Generated reports are not hand-edited.** `docs/CONNECTORS.md`, `reports/**` and `rollout/out/**` are generated.

## The held-out rule

- `heldout/blind-1/cases.yaml` was written by someone who never saw the code. Its first run is `reports/heldout/blind-1/first_run.json`; both are pinned by sha256 in `tests/test_heldout.py`.
- Never change code to pass a held-out set.
- If you study its failures, write `regression` to `heldout/blind-1/STATUS` and move the cases into `evals/`. Then have someone who has not seen the code write a new set from `heldout/WRITING_CASES.md` only.

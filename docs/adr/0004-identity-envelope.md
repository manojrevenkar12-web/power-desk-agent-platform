# 4. A signed identity envelope between the gateway and the tool Lambda

**Status:** accepted

**Context.** AgentCore Gateway calls a Lambda target with the tool arguments as the event and the tool name in the client context. The caller's identity is not passed in that context. Putting the user into the tool arguments would let a model forge it.

**Decision.**
- The REQUEST interceptor receives the request headers. It verifies the caller's JWT, strips any `_desk_identity` argument the client sent, and adds one that it signs. The signature is an HMAC with a key held only by the interceptor and the tool Lambda, kept in Secrets Manager, and it is valid for 120 seconds.
- The Lambda refuses any call without a valid envelope.
- The RESPONSE interceptor filters `tools/list` with Cedar for the same user.

**Consequences.**
- `tests/test_aws.py` covers a forged envelope, a missing envelope, a bad token and the developer surface.
- The key is rotated with both functions, as described in the runbook.

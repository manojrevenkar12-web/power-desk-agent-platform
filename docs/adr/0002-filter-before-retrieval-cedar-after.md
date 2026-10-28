# 2. Entitlement filter before retrieval, Cedar after

**Status:** accepted

**Context.** Knowledge bases mix four scopes (application, agent, user, chat) and three classifications (internal, confidential, inside information). If the system ranks first and filters afterwards, it wastes the top-k on documents the user cannot see. If it filters only by metadata, a filter bug becomes a leak.

**Decision.** `kb/entitlements.retrieval_filter` writes the user's entitlements once, as an Amazon Bedrock Knowledge Bases retrieval filter. The same filter is used in three places:
- it is passed to Bedrock `Retrieve`;
- it is compiled to SQL for pgvector;
- it is evaluated in memory.

Each hit is then checked with Cedar. A hit that the filter allows but Cedar refuses is never shown, and it is counted.

**Consequences.**
- `tests/test_policy.py` proves that the filter and Cedar agree for every document, user and context.
- The evals gate requires zero disagreements.
- Chat documents are deleted when the chat closes.
- Agent-scope documents are visible only inside the skill that owns them.

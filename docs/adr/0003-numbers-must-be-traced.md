# 3. Every number in an answer must come from a tool result or a document

**Status:** accepted

**Context.** On a trading desk, a plausible but invented number does more harm than no answer at all.

**Decision.** `grounding.verify` extracts each stated number together with its unit and scale, and looks for that value in the turn's tool results and retrieved documents. Dates, years, identifiers and legal references are not checked. If any number is untraced, the agent is sent back once with the list. Whatever is still untraced after that is removed before the user sees the answer.

**Consequences.**
- The console links every number to its tool call and JSON field.
- The ablation suite shows what reaches users without the check: 2 untraced numbers in 33 cases, against 0 with it.
- Numbers the user put in the question are exempt.
- A number that is derived but correct, such as a difference of two results, is removed unless a tool returns it. To keep it, add it to a tool.

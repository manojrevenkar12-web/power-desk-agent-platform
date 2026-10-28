---
name: imbalance-risk-check
description: Check a PPA's imbalance cost and stress it with extra forecast error. Use for questions about forecast errors, imbalance prices, reBAP exposure or balancing risk of a PPA.
allowed-tools: imbalance_exposure forecast_error search_knowledge
metadata:
  owner: risk
  version: "1.0"
---
# Imbalance risk check

1. Read the methodology: `search_knowledge` for "imbalance risk check methodology" in the agent
   scope. It is written for this skill.
2. Call `imbalance_exposure` for the PPA and period with the stress the methodology prescribes.
3. Report the realised imbalance cost, the stress's additional cost and the mean absolute spread
   between imbalance and day-ahead prices. Flag the PPA if the methodology says to.

---
name: hedge-position-check
description: Check month futures hedges against the month's settlement and against expected PPA output. Use for questions about hedge P&L, hedge ratio, over- or under-hedging.
allowed-tools: hedge_report search_knowledge
metadata:
  owner: berlin-power
  version: "1.0"
---
# Hedge position check

1. Call `hedge_report` for the month (it covers only trading books the user may read).
2. Report each hedge's settlement price and P&L, the total P&L and the hedge ratio per zone.
3. Compare the hedge ratio with the desk's target from `search_knowledge` ("hedge ratio target")
   if the user may read it, and say whether the book is over- or under-hedged.

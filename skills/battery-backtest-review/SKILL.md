---
name: battery-backtest-review
description: Backtest a battery's day-ahead arbitrage and compare a simple daily rule with the perfect-foresight optimum. Use for questions about battery or VPP revenue, cycles or strategy.
allowed-tools: battery_backtest list_book_assets search_knowledge
metadata:
  owner: vpp
  version: "1.1"
---
# Battery backtest review

1. Call `battery_backtest` for the asset and period.
2. Report the perfect-foresight revenue, the simple rule's revenue and its share of the optimum,
   and the optimum per MW and day.
3. Explain that the optimum needs hindsight and that the gap is what better scheduling could win.

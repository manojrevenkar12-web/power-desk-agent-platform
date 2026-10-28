---
name: ppa-performance-report
description: Report how the desk's PPAs performed over a period, against their strikes. Use when someone asks about PPA P&L, capture prices of our PPAs, shape discount, or which PPA did worst.
allowed-tools: list_book_assets ppa_portfolio ppa_valuation search_knowledge
metadata:
  owner: origination
  version: "2.0"
---
# PPA performance report

1. Call `ppa_portfolio` for the period (it covers only books the user may read).
2. For the PPA with the lowest P&L, call `ppa_valuation` and report its capture price, shape
   discount, energy curtailed by a negative-price clause and imbalance cost.
3. Give totals first (volume, P&L, volume-weighted capture price), then the weakest PPA.
4. If the tools refuse a book, say the user has no access to it. Never estimate it.

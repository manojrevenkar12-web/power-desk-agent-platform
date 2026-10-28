---
name: negative-price-review
description: Review negative day-ahead prices in a zone and what they cost solar or wind. Use for questions about negative hours, longest negative runs, capture rates in sunny months, or EEG section 51.
allowed-tools: negative_prices capture_price search_knowledge
metadata:
  owner: origination
  version: "1.0"
---
# Negative-price review

1. Call `negative_prices` for the zone and period.
2. Call `capture_price` for solar (or the technology asked about) over the same period.
3. Report negative hours, their share of intervals, the longest run and the lowest price, then the
   capture price, the baseload price and the capture rate, and the share of generation that fell
   in negative quarter hours.
4. For German zones, explain with `search_knowledge` ("EEG section 51 negative prices") that new
   plants get no premium in negative quarter hours and therefore curtail at zero.

---
name: explain-price-move
description: Explain why day-ahead power prices in a bidding zone were high, low or negative over a period. Use when a trader asks what drove prices, why a day was cheap or expensive, or what set the price.
allowed-tools: price_drivers price_stats search_knowledge
metadata:
  owner: berlin-power
  version: "1.2"
---
# Explain a price move

1. Call `price_drivers` for the zone and period the trader names. If they name one day, the
   period is that day to the next day.
2. Call `price_stats` for the same zone and period when they ask about the average or extremes.
3. Explain in this order: the average price; the lowest quarter hour and what set it (residual
   load, renewables, the price-setting block); the highest quarter hour and what set it; gas and
   carbon if the highs were set by thermal plants.
4. If the lowest price was negative, say whether renewables curtailed at zero or below zero, and
   look up the EEG section 51 note with `search_knowledge` if the trader asks why.

State every number exactly as the tools return it, with its unit and the local time it refers to.
Do not compute differences or averages yourself; if you need one, say which tool would give it.

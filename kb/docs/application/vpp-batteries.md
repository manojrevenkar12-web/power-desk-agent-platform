---
id: playbook-vpp
title: Batteries in the virtual power plant
classification: internal
scope: application
---
# Batteries in the virtual power plant

Our batteries earn from day-ahead arbitrage: charging when prices are low, discharging when they
are high. Two numbers frame a battery's month:

- **Perfect-foresight optimum.** The best schedule with hindsight, from a linear programme over
  each day's quarter-hourly prices, starting and ending the day half full. Nobody earns this.
- **Simple rule.** One full charge in the cheapest window of the day and one discharge in the
  dearest window after it. A floor any scheduler should beat.

The simple rule's share of the optimum tells you how much of the day's spread a basic strategy
captures. It falls when days have two price dips (morning and solar midday) that a single cycle
cannot both use. Round-trip efficiency matters: a battery at 88 percent needs the discharge
price to be well above the charge price before a cycle pays.

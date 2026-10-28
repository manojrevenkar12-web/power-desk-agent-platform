---
id: rules-15min-mtu
title: Day-ahead coupling in 15-minute products
classification: internal
scope: application
---
# Day-ahead coupling in 15-minute products

Since delivery day 1 October 2025 the Single Day-Ahead Coupling (SDAC) clears Europe's day-ahead
markets in 15-minute market time units. A delivery day has 96 quarter hours (92 or 100 on the
clock-change days). Hourly and block orders still exist, but prices are published per quarter hour.

What this means for the desk:

- Price statistics, negative-price counts and capture prices are computed per quarter hour. An
  hour with three negative quarter hours counts as 0.75 negative hours, not as one.
- Solar ramps are now priced inside the hour: the first and last quarter hours of the solar
  plateau often differ by more than the hourly average suggests.
- Battery schedules can follow the quarter-hourly shape, which raises the value of fast assets.

Day-ahead prices are bounded by the harmonised minimum clearing price of -500 EUR/MWh and a
harmonised maximum that the ACER methodology raises automatically when prices approach it.

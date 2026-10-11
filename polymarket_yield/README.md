# Polymarket "resolution yield": buying near-certain outcomes

**Status: TESTED, no edge before fees.** Yield per $1 ticket = **-0.08% +/-1.41** on n = 893.

## Hypothesis

A popular Polymarket pattern: buy outcomes that already trade at 90-99.5c a few days before
resolution and hold them to the end, collecting the last few cents. If the market under-prices
"almost certain", this is a low-variance yield on idle capital.

The arithmetic: buying at price `p` an outcome with true probability `q` has EV per $1 of
`q/p - 1`. At a fair price (`p = q`) the EV is zero; the edge exists only when the market sells
below the true probability. The payoff is skewed: at 97c a winner pays +3c and a loser costs -97c,
so one upset wipes ~32 winners. Capital is also locked until resolution (and UMA resolution can be
delayed or disputed), so for slow markets the annualised figure matters: 2% over 3 days is ~240%
annualised, 2% over 3 months is ~8%.

## Data

`poly_yield_backtest.py --fetch` (public Gamma + CLOB APIs, no key). Closed Polymarket markets with
an end date in the 12 months before the run (2025-07-12 .. 2026-07-08), collected by tag:

- soccer: epl, la-liga, serie-a, bundesliga, ligue-1, champions-league, world-cup
- esports: cs2, lol, league-of-legends, dota-2, valorant
- tennis: tennis, atp, wta
- politics: politics, geopolitics, elections

Filters: volume >= $2000, market resolved (an outcome's final price > 0.99). For **every** outcome
of every market the CLOB price 72 hours before `endDate` was taken (60-minute fidelity, closest point
in a +/-3h window). If that entry price was inside 0.90-0.995 it became a virtual $1 ticket;
`won` = that outcome's final price > 0.99. Result: **893 tickets** (one qualifying outcome per market;
median market volume ~$12k). The dataset is pure Polymarket data and is shipped in full as
`data/poly_yield_dataset.json`.

## Result

Output of `python poly_yield_backtest.py` on the shipped dataset:

| Category | n | Avg entry | Hit rate | Tail rate | Yield per $1 | 95% CI |
|---|---|---|---|---|---|---|
| soccer | 317 | 94.3c | 94.3% | 5.68% | -0.00% | +/-2.71 |
| esports | 98 | 96.2c | 96.9% | 3.06% | +0.75% | +/-3.59 |
| tennis | 19 | 95.6c | 100.0% | 0.00% | +4.70% | +/-1.44 |
| politics | 459 | 96.5c | 96.1% | 3.92% | -0.52% | +/-1.86 |
| **all** | **893** | **95.7c** | **95.6%** | **4.37%** | **-0.08%** | **+/-1.41** |

| Entry band | n | Hit rate | Yield per $1 |
|---|---|---|---|
| 0.90-0.95 | 351 | 91.7% | -1.04% |
| 0.95-0.98 | 273 | 97.1% | +0.70% |
| 0.98-0.995 | 258 | 99.2% | +0.37% |

| Market type | n | Hit rate | Yield per $1 |
|---|---|---|---|
| negRisk (multi-outcome) | 519 | 94.8% | -1.03% |
| binary | 374 | 96.8% | +1.23% +/-1.90 |

Reading:

- The average entry of 95.7c implied a 95.7% hit rate; the realised hit rate was 95.6%. The market
  is priced correctly at this horizon, the "yield" is a fair coupon, and the 4.4% of tails pay for it.
- The 90-95c band is slightly negative and the multi-outcome (negRisk) markets are slightly negative;
  the binary +1.23% and the tennis +4.7% (n = 19) are inside the noise.
- The 39 losing tickets are what you would expect: "No" on exact-score markets at 90-95c, spreads and
  totals that flipped late, and politics brackets about weekly post counts.
- **Fees and slippage are not included.** At the time of the test Polymarket charged a taker fee on
  sports markets (the research notes put it at roughly 3%), which pushes the soccer and esports rows
  clearly negative; politics markets were mostly fee-free. Entering as a maker would recover part of
  that, at the cost of not always being filled.

**Verdict: no edge at a 72-hour horizon.** Buying near-certain outcomes on Polymarket in 2025-26
earned the implied probability and nothing more. The `resolution_monitor.py` scanner in
`../polymarket_scanners` was built for this pattern before the backtest and is kept as a research
tool, not a signal.

Untested variants the script supports: `--hours 168` (enter a week out) and `--outrights` (only
"winner / reach the final" markets, band widened to 0.80+).

## Files

| File | What it does | Needs |
|---|---|---|
| `poly_yield_backtest.py` | Default: offline summary of `--data` (shipped file). `--fetch`: rebuild the dataset (30-60 min) | nothing for the summary; Polymarket public APIs for `--fetch` |
| `data/poly_yield_dataset.json` | 893 tickets: category, market slug/question, outcome, entry price, won, end timestamp, volume, negRisk flag | - |

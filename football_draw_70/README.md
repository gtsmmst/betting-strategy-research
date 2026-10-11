# Football: backing the draw from a 1-goal lead at 70'

**Status: CLOSED (2026-07-08). No edge.** The conditional probabilities were real; the market already
prices them.

## Hypothesis

When a football match is exactly one goal apart around the 70th minute, it ends in a draw roughly
one time in five. The idea was that prediction-market prices "respect the scoreline" and sell the
draw too cheaply in that spot, especially when the side that leads is *not* the favourite.

## Step 1: conditional draw probabilities (API-Football, 2021-2023)

`draw_backtest.py`. Data: 5 top leagues (EPL, La Liga, Serie A, Bundesliga, Ligue 1) x seasons 2021,
2022, 2023. Cut at minute 70 with a lead of exactly 1 goal. Own goals credited to the opponent.
"Favourite" = final league position (a gap of >= 6 places).

Base rates (from an earlier, smaller run of the same script, n = 1282 situations):

| Outcome after a 1-goal lead at 70' | Share |
|---|---|
| Draw | 19.5-19.6% |
| Leader holds | ~72% |
| Comeback (leader loses) | ~8% |

Stable across leagues (17-22%). By scoreline: 1-0 -> 18.2%, 2-1 -> 23.2%.

Split by who is leading (full run, n = 1928):

| Leader | n | Draw | 95% CI |
|---|---|---|---|
| Favourite (>= 6 places higher in the table) | 719 | **13.5%** | +/-2.5 |
| Even (gap <= 5 places) | 901 | **21.9%** | +/-2.7 |
| Underdog | 308 | **26.9%** | +/-5.0 |

The favourite interval does not overlap the even/underdog intervals, so the split is real: a strong
side leading 1-0 nearly always closes the game out; an even or weaker side often does not.

Monte Carlo from those probabilities (1% of bankroll per bet, 300 bets, 4000 runs), **assuming** the
draw could be bought at the prices in the first column:

| Scenario | EV/bet | Median bankroll | 5th percentile | Max drawdown (median / p95) |
|---|---|---|---|---|
| Underdog leads, draw @18c (p = 27%) | +50% | x4.3 | x2.2 | 16% / 23% |
| Even, @17c (p = 22%) | +29% | x2.5 | x1.24 | 22% / 34% |
| Even, @20c (p = 22%) | +10% | x1.4 | x0.77 | 24% / 42% |
| Favourite, @13c (p = 13.5%) | +4% | x1.05 | x0.46 | 38% / 61% |

Longest losing streak at p95: 25-30 bets in the thin scenarios. The derived "rule" was: back the draw
at 65-75' with a 1-goal lead when the leader is not a clear favourite and the price is below the
breakeven of the bucket (even ~22c, underdog ~27c; favourite ~13.5c = skip).

Side result: comebacks (leader loses) run at ~8% overall and are more frequent when the trailing side
is the favourite. This was never tested against prices and stays an idea.

**The flaw in step 1:** it assumed the market price. Step 2 measured it.

## Step 2: real Polymarket prices (seasons 2024-25 and 2025-26)

`draw_poly_backtest.py`. Stage A rebuilds the same setups for seasons 2024 and 2025. Stage B matches
each setup to its Polymarket event (Gamma API, by league tag + date + team names), finds the draw
market, pulls the Yes-token price history from the CLOB at 1-minute fidelity and records the price
closest to kickoff + 87 min (roughly the 70th minute of play; window +78..+95 min) plus the
pre-match price.

Coverage: 1486 setups across the two seasons; a Polymarket event with a price in the window existed
for **652** of them (833 had no Polymarket listing at all, 1 had an event but no price). Season
2024-25 contributes only 138 priced rows, 133 of them EPL (Polymarket listed little other top-league
football that season, and only from October 2024); in 2025-26 the EPL, La Liga, Bundesliga and
Ligue 1 were matched but Serie A was not matched to a single Polymarket event, so Serie A is
effectively absent (its 2 priced rows from 2024-25 both show an implausible 50c).
Rows where a goal was scored between 70' and the start of the price window (`goals_70_78`) are
dropped by default because the ~70' price is stale; that leaves **517** clean rows.

Output of `draw_poly_analyze.py` on the full two-season dataset (clean rows):

| Leader | n | P(draw) | 95% CI | Avg Polymarket draw price at ~70' | EV(avg) | EV per $1 ticket |
|---|---|---|---|---|---|---|
| Favourite | 202 | 15.3% | +/-5.0 | 19.7c | -21.9% | -14.0% +/-29.6 |
| Even | 241 | 21.2% | +/-5.2 | 25.4c | -16.7% | -12.3% +/-22.4 |
| Underdog | 74 | 29.7% | +/-10.4 | 28.3c | +5.0% | +26.9% +/-56.5 |
| All | 517 | 20.1% | +/-3.5 | 23.6c | **-14.7%** | -7.4% +/-17.6 |

Same with the stale rows kept (`--keep-grey`, n = 652): P(draw) 21.8%, average price 23.4c,
EV(avg) -7.1%, EV per ticket +1.2% +/-16.4.

`EV(avg) = P(draw) / average price - 1`. `EV per $1 ticket` = mean P&L of buying one $1 ticket in
every row (+(1/price - 1) on a draw, -1 otherwise) with its 95% CI.

Reading:

- The conditional probabilities **replicated** out of sample (even 21.2% vs 21.9% in 2021-23,
  underdog 29.7% vs 26.9%, favourite 15.3% vs 13.5%; on the 2025-26 season alone the even bucket
  came out at exactly 21.9%, n = 192).
- The market was not asleep. Across all buckets the draw traded at 23.6c against a realised 20.1%,
  i.e. the buyer of the draw paid roughly 3.5c too much per share: EV between -7% and -15%
  depending on how stale rows are treated. The market priced "even" at 25.4c, not the 17-20c the
  Monte Carlo had assumed.
- The one positive pocket, underdog leads, shows +26.9% per ticket on n = 74 with a +/-56.5
  confidence interval (and only +5.0% on the bucket-average definition). On the 2025-26 season
  alone it had looked like +37.0% +/-66.2 (n = 61); adding 2024-25 shrank it, and it is
  statistically indistinguishable from zero.
- Applying the original rule ("even" bucket, price below the 22c breakeven) selects 93 rows with
  P(draw) 18.3% at an average price of 18.4c: EV about 0%. The cheap draws were cheap for a reason.

**Verdict: no edge. Strategy closed on 2026-07-08.**

The lesson that became a house rule for every later idea in this repo: a hypothesis is not a
strategy until it has been run against the venue's *real* historical prices with confidence
intervals. Doing so cost $0 instead of a bankroll.

## Files

| File | What it does | Needs |
|---|---|---|
| `draw_backtest.py` | Step 1: conditional probabilities + EV table + Monte Carlo | `API_FOOTBALL_KEY` |
| `draw_poly_backtest.py` | Step 2 data collection: setups for one season + Polymarket prices -> `draw_poly_dataset_<season>.json` | `API_FOOTBALL_KEY` (stage A); Polymarket public APIs (stage B) |
| `draw_poly_analyze.py` | Offline analysis of one or more dataset files (`--data`, `--keep-grey`, `--by league/score`, `--max-price`) | nothing |
| `draw_live_scanner.py` | Live alerting for the setup (kept as a research tool; see verdict) | `API_FOOTBALL_KEY` |
| `data/samples/draw_poly_dataset_sample.json` | 20-row sample of the step-2 dataset (schema reference) | - |

### About the data

The full step-2 datasets (1486 rows) contain per-match scores at 70' and full-time results that were
pulled from API-Football, a paid provider, so they are **not** shipped. `data/samples/` holds a
20-row stratified sample (5 favourite / 10 even / 5 underdog rows, all with a Polymarket price) so
the schema and the analysis script can be exercised. To rebuild the full dataset with your own key:

```
cp .env.example .env            # put your key in API_FOOTBALL_KEY
export $(cat .env | xargs)
cd football_draw_70
python draw_poly_backtest.py --season 2024 --out-dir data/raw
python draw_poly_backtest.py --season 2025 --out-dir data/raw
python draw_poly_analyze.py --data data/raw/draw_poly_dataset_2024.json data/raw/draw_poly_dataset_2025.json
```

Running `draw_poly_analyze.py` with no arguments uses the 20-row sample. It runs, but with n = 16
clean rows the output is noise (for example the sample shows the favourite bucket at +60% EV on 4
rows); the numbers in this README come from the full dataset.

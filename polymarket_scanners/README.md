# Polymarket scanners (tools, not strategies)

Four stand-alone scripts that query Polymarket's public Gamma and CLOB APIs (no key, standard
library only) and print candidate lists. None of them places orders or touches keys. They were
built as reconnaissance for the ideas listed below; only one of those ideas was later backtested
(see the status column).

| Script | Pattern | Status of the idea |
|---|---|---|
| `poly_arb_scanner.py` | (1) neg-risk arbitrage: on a multi-outcome event the sum of best asks < $1; (2) resolution yield: outcomes at 94-99.5c with <= 21 days to resolution, with annualised yield; (3) markets with liquidity rewards | (1) tool only, results were never logged systematically; (2) backtested in `../polymarket_yield`: no edge; (3) idea only |
| `resolution_monitor.py` | Polls active markets in ~35 tags, finds the near-$1 side (97-99c sport/esports, 95-99c slow categories), measures real order-book depth from the CLOB `/book`, prints yield, annualised yield, fillable $, time to resolution, fee; logs alerts | Pattern backtested in `../polymarket_yield`: **-0.08% yield before fees**. Kept as a research tool |
| `poly_convex_scanner.py` | Cheap tails (1-20c, default) in slow markets with liquidity, sorted by liquidity x multiple; cheap "fields" (negRisk events with >= 4 cheap contenders). `--lo 0.001 --hi 0.01` gives the 0.1-1c tail-lottery universe | Idea only. Never got past "candidate list"; no model of true probability was built, so no backtest |
| `poly_mm_scanner.py` | Markets with liquidity rewards enabled: daily pool, `rewardsMinSize`, `rewardsMaxSpread`, competing liquidity, and a rough APR estimate on the capital tied up | Idea only. Never run with real quotes; the APR formula is a ranking heuristic, not Polymarket's actual reward formula |

## Usage

```
python poly_arb_scanner.py --help
python poly_arb_scanner.py --limit 300 --tag soccer
python resolution_monitor.py --once --min-fill 500
python poly_convex_scanner.py --lo 0.001 --hi 0.01 --min-days 7
python poly_mm_scanner.py --min-pool 5 --top 15
```

All scripts need outbound HTTPS to `gamma-api.polymarket.com` (and `clob.polymarket.com` for the
monitor). They were verified to compile and to print `--help` in a sandbox without network access;
output formats may drift if Polymarket changes its API fields (the MM scanner already reads the daily
reward pool from several possible field names for that reason).

## Notes that came out of using them

- The 99-99.9c band at the moment of resolution is taken by low-latency bots; a human cannot
  compete there. The scanners therefore cut the band off at 99c and look for spots where price and
  capital matter more than milliseconds (slow markets, niche leagues, deep books at 95-99c). The
  yield backtest then showed that even that band is fairly priced.
- Correlation is the main sizing risk for near-certain buying: several sub-markets of the same match
  are one bet, not many.
- For cheap tails, "cheap" is not "undervalued"; the scanner only narrows the universe. A real test
  would need an independent probability estimate per candidate, which was never built.

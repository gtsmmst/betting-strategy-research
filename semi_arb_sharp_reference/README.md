# Semi-arb against a sharp reference ("be the house")

**Status: hypothesis (2026-07-11) -> paper forward test (2026-08-07 .. 2026-09-06) -> not working
in the tested form (core rule ROI -19.4% on n = 25).** No code in this folder: the paper pipeline
ran inside a private scanner; what is public here is the reasoning, the variance math and the
numbers.

## Mechanics

A *sharp* bookmaker is one that does not ban winning customers but uses them: professionals bet
large, the book moves its line after them, and its closing line becomes the best public estimate
of the probability. The classic skill test for a bettor is "beat the closing line": if your entries
are consistently better than the sharp close you have an edge; if not, you are a tourist no matter
what the P&L chart looks like.

*Semi-arb*: if a prediction market sells an outcome at 39c while the sharp-implied probability is
42%, buying at 39c has an expectation of +3c per share **without a hedge**. You are not guessing the
result, you are selling insurance above cost. Any single ticket can lose, just as any single roll
can win against the casino; the house does not win every roll, it wins the flow.

## Variance: how many bets before "almost surely" in profit

Stake 1 share ($1 payout), true edge `e` per bet, hit probability `p`. Per bet: EV = `e`,
standard deviation `s1 = sqrt(p(1-p))`. Over N independent bets: EV = `N*e`, sd = `sqrt(N)*s1`.
To be above zero at ~2 sd (97.7%):

    N > (2 * s1 / e)^2

| Bet type | p | s1 | edge 2% | edge 3% | edge 5% |
|---|---|---|---|---|---|
| Coin flips (odds ~2.0) | 0.50 | 0.50 | **2,500 bets** | 1,110 | 400 |
| Favourites (odds ~1.18) | 0.85 | 0.36 | 1,270 | 570 | 205 |
| Heavy favourites (odds ~1.05) | 0.95 | 0.22 | **475 bets** | 210 | 76 |

Consequences:

- 1,000 coin-flip bets with a 2% edge is only 1.26 sd: roughly a 10% chance of being down after all of
  them, with drawdowns on the way guaranteed.
- Favourites are the "shortest" path: less variance per dollar of payout, 2-sd confidence after
  hundreds rather than thousands of bets. Example: 500 bets of $200 on favourites with an honest
  +2%: EV +$2,000, sd ~$980, 95% range about [+$40 .. +$3,960]. The same volume on coin flips:
  sd ~$2,240, range [-$2,500 .. +$6,500].
- Correlation is killer number one: 20 sub-markets of one match are one bet, not twenty.
  Diversification counts independent *events*.
- A false edge is killer number two: if the "+3%" is an error in your estimate rather than in the
  market, the law of large numbers works against you. So the edge has to be measured before money
  is risked, which is what the paper test below did.

## Where a sharp reference comes from (no bookmaker account needed)

Only the *price* is needed, not an account: odds-API aggregators carry sharp-book lines on a free or
cheap tier; a de-vigged consensus of several soft books is a free "pseudo-sharp" that is good enough
for a backtest (worse than a true sharp line because soft books copy each other with a lag).

Sizing rules that were written down for the live version, had it ever reached money: at most 1% of
bankroll per independent event; one match = one risk; only markets with real order-book depth; no
entries in news windows or in-play; log every ticket with the reference price at entry.

## Paper forward test (2026-08-07 .. 2026-09-06)

Rule v1: on tier-2/3 CS2 pre-match markets, buy the underdog on Polymarket when its ask is at least
2c below the fair probability implied by the sharp reference. Virtual tickets of $25, resolved
against the actual market outcomes.

| Segment | n | P&L | ROI | Verdict |
|---|---|---|---|---|
| CORE (rule v1 as written) | 25 | -$121.51 on $625 | **-19.4%** | not working; 5 consecutive losses on tier-3 South-American underdogs with a large delta |
| TIER-1 flags (outside the v1 universe: compressed asks on upsets) | 5 | +$453.63 on $125 | +363% | the only positive pocket, but n = 5 is not statistics |
| ANCHORED = CORE + TIER-1 | 30 | +$332 on $750 | +44% | the whole profit is the 5 flags |
| NO-ANCHOR (no sharp reference) | 18 | -$18.89 on $450 | -4% | noise |

The green-light threshold had been set in advance at ROI >= +4% on CORE after two weeks; it was never
met at any check from 2026-08-21 onwards. Honest summary: a sharp-fair anchor on tier-2/3 CS2 does
not give an edge over Polymarket asks; the niche is thinner than the hypothesis assumed. A possible
follow-up, not run, would be tier-1 "compressed asks" as its own hypothesis with n >= 30.

The sample sizes here are far below the N from the variance table above, which is exactly why the
conclusion is "not working *as specified*" rather than "disproven": the core rule lost money at a
rate that made continuing pointless, not at a rate that is statistically conclusive.

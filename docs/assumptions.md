# Assumptions and calibration

Everything here is a choice I made, with the reason. Nothing is a real
institution, client or price.

## The book

Twelve borrowers, $42.0B on loan at the previous close. Four lent
classes: US Treasuries, IG corporate bonds, US large cap equities, US
small cap equities. Five collateral classes: cash, US Treasuries, IG
corporate bonds, US large cap equities, high yield bonds. Equities and
high yield as collateral are tagged non-standard.

The mix is fixed-income heavy on purpose. Agency lending programs lend
far more government bonds by value than equities, and a large share of
that is against non-cash collateral.

Each borrower has a habitual buffer of 0 to 3% above the requirement.
Some borrowers post exactly what is asked and get called every time the
market moves, and some keep a cushion. Dogwood and Rowan keep none, which is
why they are called on the as-of day.

Position count per borrower is on loan divided by 60, clipped to 8 and
150, so about 700 loans in total. Sizes are lognormal within each pair
and scaled to the borrower's mix exactly.

## Prices

Three years of business days ending 31 December 2025. Three common
factors (equity, rates, credit) with Student t shocks (5 degrees of
freedom, scaled to unit variance) so tails are fat, clipped at five
standard deviations so no single draw prints a one-day move larger than
any real market has. Each class index loads on the factors:

| class | equity | rates | credit | own noise |
|---|---|---|---|---|
| US Treasuries | | 1.0 | | |
| IG corporate | | 0.9 | 0.9 | 0.05% |
| High yield | 0.25 | 0.3 | 1.5 | 0.10% |
| Large cap equity | 1.0 | | | 0.40% |
| Small cap equity | 1.2 | | | 0.60% |

Daily factor volatility: equity 1.0%, rates 0.25%, credit 0.30%.

Each class then has two baskets, lent and received, each the index plus
its own basket noise (Treasuries 0.05%, IG 0.15%, large cap 0.50%,
small cap 0.70%, high yield 0.30%). Without that, a large cap loan
against large cap collateral would have zero spread risk, which is not
true of two different baskets of stocks.

A stress episode is planted from day 330 to day 372 (six weeks in the
second year): factor volatility doubles, equities drift down 0.6% a day,
credit 0.2% a day, Treasuries drift up 0.1% a day. The seed was chosen
from a scan so the episode reads like 2020, not 1929.

The as-of day (the last day) carries an added rally shock: equity factor
up 2.5%, rates up 0.3%, credit up 0.4%. A lender is exposed when the
securities it lent out rise, so a rally is the day the margin calls go
out. Without it the monitor would show a quiet day.

Cash is 100 every day. Interest on cash collateral is ignored.

## House margin schedule

102% for cash and Treasuries, 105% for everything else. This is the
convention in US agency lending: 102% for same-currency cash, 105% for
non-cash or cross-currency. Required collateral is on loan times the
schedule for that collateral class.

## Load checks

Twenty checks in four families, run at every load. Any failure blocks
the load and names itself.

Record counts: prices, positions and borrowers in the database equal
what the source wrote, and there are at least 700 distinct price dates.

Control totals: total on loan ties to the source and to the static
config within a millionth. On loan and collateral per borrower tie to
the source figures. Collateral equals on loan times the requirement
times one plus the borrower's buffer.

Completeness: no null fields on a position, no non-positive loan or
collateral, no null or non-positive price, every series on every date,
no one-day move beyond 40% in any class (a data error, not a market),
and no traded series printing the same close three days running (a feed
that stopped, not a quiet market, and cash is exempt).

Reference data: no position id loaded twice, every position keys to a
borrower in the borrowers table, every loan and collateral class is a
known class, every borrower has positions and a positive limit.

## Planted breaks

Three, each loaded alone into a staging copy and run through the same
checks with the clean source totals as the expected values. The
exposure report is recomputed on the broken copy and compared with the
clean one, and the borrower that moved most is the one reported.

1. Duplicate: Alder's largest position appears twice. Alder sits at 90%
   of its limit, so the duplicate is the one most likely to tip a
   borrower over. It does not on this book ($301M overstated, limit used
   93%), so the severity is medium: risk overstated, business blocked.
2. Orphan: Dogwood's largest position is keyed to borrower B99, which
   reference data does not know. The exposure roll-up joins positions to
   borrowers, so the loan drops out silently and Dogwood, which is over
   its limit on the clean load, no longer is. High severity.
3. Frozen feed: the last three closes of the large cap lent basket are
   the close before them. The as-of day is a rally, so every borrower
   lending large caps is marked flat instead of up. Birch's $49M margin
   call, the largest on the book, is not raised. High severity.

Severity rule: high if the break understates on loan or a margin call
on the most affected borrower, or hides a limit breach. Medium if it
overstates on loan. Low otherwise.

Remediation due date is ten business days from raised. That is a
placeholder for whatever the house SLA is.

## Limits

Exposure limit per borrower by credit grade. Non-standard collateral
cap by grade: 35% for A names and the BBB names that post equity
collateral, 25% for the HY-heavy BBB fund, 20% for BB. Near means
within 10% of the limit or cap.

## Simplifications I would name first

1. Daily marks, not intraday. The monitor runs at the close.
2. One price series per asset class and side, not per security. A
   basket, not a stock.
3. The breaks are planted, so the root cause is known. On a real feed
   the root cause is what the analyst writes after tracing the break
   upstream, and the concern is open until then.

Also: no cash collateral reinvestment, no FX, no term loans, no
rehypothecation, no wrong-way risk between borrower and collateral, no
intraday feed timing.

"""Synthetic prices and positions for the lending book.

Prices: three years of business days, one index per asset class driven
by three common factors (equity, rates, credit) with fat-tailed shocks,
and a planted six-week stress episode in the second year where equities
and credit sell off, volatility triples and Treasuries rally. Every
class then has two baskets, the securities lent out and the securities
received as collateral, each the index plus its own basket noise.

Positions: for every borrower, a few dozen to a few hundred individual
loans split across the borrower's (loan class, collateral class) mix.
Collateral is what the borrower held at the previous close, which is the
requirement plus that borrower's habitual buffer. The as-of day's price
move is what the exposure monitor then marks.

Fixed seed, so every run is the same book.
"""

import numpy as np
import pandas as pd

from lab.book import ASSET_CLASSES, BORROWERS, MARGIN_REQUIREMENT

SEED = 19
N_DAYS = 756                      # three trading years
END_DATE = "2025-12-31"
STRESS_START, STRESS_END = 330, 372   # day indices of the planted episode
T_DF = 5                          # student t degrees of freedom for shocks
SHOCK_CLIP = 5.0                  # winsorize shocks at five standard deviations

# factor volatilities (daily) in calm markets and the stress multiplier
FACTOR_VOL = {"equity": 0.0100, "rates": 0.0025, "credit": 0.0030}
STRESS_VOL_MULT = {"equity": 2.0, "rates": 2.0, "credit": 2.0}
# daily drift added inside the episode: equities and credit fall,
# Treasuries rally (flight to quality)
STRESS_DRIFT = {"equity": -0.006, "rates": 0.0010, "credit": -0.0020}
# ordinary drift outside the episode: equities and credit earn something
CALM_DRIFT = {"equity": 0.0005, "rates": 0.0, "credit": 0.0002}
# the as-of day is a sharp rally on purpose. a lender is exposed when the
# securities it lent out go up (it would cost more to buy them back), so
# a rally is the day the margin calls go out, and the monitor has
# something to show
AS_OF_SHOCK = {"equity": 0.025, "rates": 0.003, "credit": 0.004}

# class index = loadings on the factors + own noise (daily vol)
LOADINGS = {
    "ust":         {"rates": 1.0, "own": 0.0},
    "ig_corp":     {"rates": 0.9, "credit": 0.9, "own": 0.0005},
    "hy_corp":     {"rates": 0.3, "credit": 1.5, "equity": 0.25, "own": 0.001},
    "us_large_eq": {"equity": 1.0, "own": 0.004},
    "us_small_eq": {"equity": 1.2, "own": 0.006},
}


def _t_shocks(rng, size):
    """Unit-variance student t draws, clipped. Five degrees of freedom
    gives fat tails; the clip stops a single draw producing a one-day
    move no real market has ever printed."""
    scale = np.sqrt((T_DF - 2) / T_DF)
    return np.clip(rng.standard_t(T_DF, size=size) * scale,
                   -SHOCK_CLIP, SHOCK_CLIP)


def generate_prices(seed=SEED):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=END_DATE, periods=N_DAYS)
    n = len(dates)
    in_stress = np.zeros(n, dtype=bool)
    in_stress[STRESS_START:STRESS_END] = True

    factors = {}
    for name, vol in FACTOR_VOL.items():
        shocks = _t_shocks(rng, n) * vol
        shocks[in_stress] *= STRESS_VOL_MULT[name]
        shocks[in_stress] += STRESS_DRIFT[name]
        shocks[~in_stress] += CALM_DRIFT[name]
        shocks[-1] += AS_OF_SHOCK[name]
        factors[name] = shocks

    rows = []
    for cls, load in LOADINGS.items():
        idx = np.zeros(n)
        for f, w in load.items():
            if f == "own":
                continue
            idx += w * factors[f]
        idx += _t_shocks(rng, n) * load["own"]
        bvol = ASSET_CLASSES[cls]["basket_vol"]
        for side in ("loan", "collateral"):
            basket = idx + _t_shocks(rng, n) * bvol
            basket[0] = 0.0
            price = 100.0 * np.exp(np.cumsum(basket))
            rows.append(pd.DataFrame({
                "date": dates, "asset_class": cls, "side": side,
                "price": price}))
    # cash is cash: it does not move. we ignore the interest on it.
    for side in ("loan", "collateral"):
        rows.append(pd.DataFrame({
            "date": dates, "asset_class": "cash", "side": side,
            "price": np.full(n, 100.0)}))
    prices = pd.concat(rows, ignore_index=True)
    prices["date"] = pd.to_datetime(prices["date"])
    return prices


def generate_borrowers():
    rows = []
    for bid, b in BORROWERS.items():
        rows.append({
            "borrower_id": bid, "name": b["name"], "type": b["type"],
            "grade": b["grade"], "limit": float(b["limit"]),
            "nonstd_cap": b["nonstd_cap"], "buffer": b["buffer"]})
    return pd.DataFrame(rows)


def generate_positions(seed=SEED):
    """One row per loan. loan_prev and coll_prev are USD millions at the
    previous close; the collateral is the house requirement times one plus
    the borrower's buffer, because that is what the borrower had posted
    before today's move."""
    rng = np.random.default_rng(seed + 1)
    rows = []
    pid = 0
    for bid, b in BORROWERS.items():
        n_pos = int(np.clip(round(b["on_loan"] / 60), 8, 150))
        for (loan_cls, coll_cls), w in b["mix"].items():
            k = max(1, round(n_pos * w))
            raw = rng.lognormal(mean=0.0, sigma=0.8, size=k)
            sizes = raw / raw.sum() * b["on_loan"] * w
            req = MARGIN_REQUIREMENT[coll_cls]
            for s in sizes:
                pid += 1
                rows.append({
                    "position_id": f"P{pid:04d}", "borrower_id": bid,
                    "loan_class": loan_cls, "coll_class": coll_cls,
                    "loan_prev": float(s),
                    "coll_prev": float(s * req * (1 + b["buffer"])),
                    "haircut_req": req})
    return pd.DataFrame(rows)


def control_totals(prices, borrowers, positions):
    """Numbers computed at generation time that the loader must find
    again in the database."""
    per_borrower = positions.groupby("borrower_id")["loan_prev"].sum()
    coll_expected = {}
    for bid, b in BORROWERS.items():
        sub = positions[positions.borrower_id == bid]
        coll_expected[bid] = float(
            (sub["loan_prev"] * sub["haircut_req"] * (1 + b["buffer"])).sum())
    return {
        "n_prices": len(prices),
        "n_dates": prices["date"].nunique(),
        "n_series": prices.groupby(["asset_class", "side"]).ngroups,
        "n_borrowers": len(borrowers),
        "n_positions": len(positions),
        "on_loan_total": float(positions["loan_prev"].sum()),
        "on_loan_by_borrower": {k: float(v) for k, v in per_borrower.items()},
        "coll_by_borrower": coll_expected,
    }

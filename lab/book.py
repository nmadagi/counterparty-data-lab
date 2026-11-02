"""Static configuration of the synthetic securities lending book.

Money is USD millions everywhere in the engine; the app formats to $B and
$M. Nothing here is a real institution, client or price.

Two sides to every position: the securities lent out (the loan side)
and what the borrower posted against them (the collateral side). Each
side is a basket drawn from an asset class. The class index moves both
baskets, but the baskets are not the same securities, so each carries
its own basket noise on top.
"""

# daily_vol is the class index; basket_vol is the extra noise that
# separates the lent basket from the received basket of the same class
ASSET_CLASSES = {
    "cash": {
        "label": "Cash (USD)", "loanable": False, "collateral": True,
        "nonstandard": False, "basket_vol": 0.0},
    "ust": {
        "label": "US Treasuries", "loanable": True, "collateral": True,
        "nonstandard": False, "basket_vol": 0.0005},
    "ig_corp": {
        "label": "IG corporate bonds", "loanable": True, "collateral": True,
        "nonstandard": False, "basket_vol": 0.0015},
    "us_large_eq": {
        "label": "US large cap equities", "loanable": True,
        "collateral": True, "nonstandard": True, "basket_vol": 0.005},
    "us_small_eq": {
        "label": "US small cap equities", "loanable": True,
        "collateral": False, "nonstandard": True, "basket_vol": 0.007},
    "hy_corp": {
        "label": "High yield bonds", "loanable": False, "collateral": True,
        "nonstandard": True, "basket_vol": 0.003},
}

LOAN_CLASSES = [k for k, v in ASSET_CLASSES.items() if v["loanable"]]
COLLATERAL_CLASSES = [k for k, v in ASSET_CLASSES.items() if v["collateral"]]


def label(cls):
    return ASSET_CLASSES[cls]["label"]


# the house margin schedule: one number per collateral type. 102 for cash
# and treasuries, 105 for everything else, the US agency lending convention
MARGIN_REQUIREMENT = {
    "cash": 1.02, "ust": 1.02, "ig_corp": 1.05, "us_large_eq": 1.05,
    "hy_corp": 1.05,
}


# borrowers. on_loan is USD millions at the previous close. limit is the
# maximum on loan allowed for that credit grade. nonstd_cap is the share
# of collateral that may be non-standard. buffer is how much extra
# collateral the borrower keeps above the requirement (some post exactly
# what is asked, some keep a cushion so they are not called every day).
# mix is the split of the loan book across (loan class, collateral class)
BORROWERS = {
    "B01": {"name": "Alder", "type": "broker dealer", "grade": "A",
            "on_loan": 9000, "limit": 10000, "nonstd_cap": 0.30,
            "buffer": 0.005,
            "mix": {("ust", "ust"): 0.55, ("ust", "cash"): 0.30,
                    ("ig_corp", "cash"): 0.15}},
    "B02": {"name": "Birch", "type": "hedge fund", "grade": "BBB",
            "on_loan": 5500, "limit": 6000, "nonstd_cap": 0.35,
            "buffer": 0.01,
            "mix": {("us_large_eq", "cash"): 0.50,
                    ("us_small_eq", "cash"): 0.20,
                    ("us_large_eq", "us_large_eq"): 0.30}},
    "B03": {"name": "Cedar", "type": "broker dealer", "grade": "A",
            "on_loan": 6000, "limit": 8000, "nonstd_cap": 0.30,
            "buffer": 0.02,
            "mix": {("ust", "cash"): 0.40, ("ust", "ust"): 0.40,
                    ("us_large_eq", "cash"): 0.20}},
    "B04": {"name": "Dogwood", "type": "hedge fund", "grade": "BB",
            "on_loan": 2500, "limit": 2500, "nonstd_cap": 0.20,
            "buffer": 0.0,
            "mix": {("us_small_eq", "hy_corp"): 0.40,
                    ("us_small_eq", "cash"): 0.30,
                    ("us_large_eq", "hy_corp"): 0.30}},
    "B05": {"name": "Elm", "type": "bank", "grade": "A",
            "on_loan": 4500, "limit": 7000, "nonstd_cap": 0.35,
            "buffer": 0.015,
            "mix": {("ust", "ust"): 0.60, ("ig_corp", "ust"): 0.40}},
    "B06": {"name": "Fir", "type": "hedge fund", "grade": "BBB",
            "on_loan": 3000, "limit": 4000, "nonstd_cap": 0.35,
            "buffer": 0.01,
            "mix": {("us_large_eq", "cash"): 0.50,
                    ("us_large_eq", "us_large_eq"): 0.30,
                    ("ig_corp", "cash"): 0.20}},
    "B07": {"name": "Hazel", "type": "broker dealer", "grade": "BBB",
            "on_loan": 3500, "limit": 5000, "nonstd_cap": 0.30,
            "buffer": 0.005,
            "mix": {("ust", "cash"): 0.30, ("ig_corp", "ig_corp"): 0.40,
                    ("us_large_eq", "ig_corp"): 0.30}},
    "B08": {"name": "Juniper", "type": "hedge fund", "grade": "BB",
            "on_loan": 1500, "limit": 2000, "nonstd_cap": 0.20,
            "buffer": 0.03,
            "mix": {("us_small_eq", "cash"): 0.60,
                    ("us_large_eq", "cash"): 0.40}},
    "B09": {"name": "Larch", "type": "bank", "grade": "A",
            "on_loan": 3000, "limit": 5000, "nonstd_cap": 0.35,
            "buffer": 0.02,
            "mix": {("ust", "ust"): 1.0}},
    "B10": {"name": "Maple", "type": "broker dealer", "grade": "A",
            "on_loan": 2200, "limit": 4000, "nonstd_cap": 0.35,
            "buffer": 0.01,
            "mix": {("ust", "cash"): 0.50,
                    ("us_large_eq", "us_large_eq"): 0.30,
                    ("ig_corp", "cash"): 0.20}},
    "B11": {"name": "Rowan", "type": "hedge fund", "grade": "BBB",
            "on_loan": 1000, "limit": 1500, "nonstd_cap": 0.25,
            "buffer": 0.0,
            "mix": {("us_small_eq", "hy_corp"): 0.50,
                    ("us_small_eq", "cash"): 0.50}},
    "B12": {"name": "Willow", "type": "asset manager", "grade": "A",
            "on_loan": 300, "limit": 2000, "nonstd_cap": 0.35,
            "buffer": 0.02,
            "mix": {("ig_corp", "cash"): 0.50,
                    ("us_large_eq", "cash"): 0.50}},
}


def total_on_loan():
    return sum(b["on_loan"] for b in BORROWERS.values())

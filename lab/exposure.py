"""Counterparty exposure monitor: mark every position at the as-of close
and roll it up per borrower against the margin requirement and the
limits.

The borrower posted collateral at the previous close equal to the
requirement plus its habitual buffer. Today's prices move the lent
securities and the collateral. If the collateral now covers less than
the requirement, the difference is the margin call that goes out this
morning. Everything here is SQL on the validated tables; pandas only
carries the result.
"""

import pandas as pd

from lab.book import ASSET_CLASSES

MARK_SQL = """
WITH last_two AS (
    SELECT DISTINCT date FROM prices ORDER BY date DESC LIMIT 2
),
as_of_day AS (SELECT max(date) AS d FROM last_two),
prev_day AS (SELECT min(date) AS d FROM last_two),
moves AS (
    SELECT p1.asset_class, p1.side, p1.price / p0.price AS ratio
    FROM prices p1
    JOIN prices p0 ON p0.asset_class = p1.asset_class AND p0.side = p1.side
    WHERE p1.date = (SELECT d FROM as_of_day) AND p0.date = (SELECT d FROM prev_day)
)
SELECT
    q.position_id, q.borrower_id, q.loan_class, q.coll_class,
    q.haircut_req,
    q.loan_prev, q.coll_prev,
    q.loan_prev * ml.ratio AS loan_asof,
    q.coll_prev * mc.ratio AS coll_asof
FROM positions q
JOIN moves ml ON ml.asset_class = q.loan_class AND ml.side = 'loan'
JOIN moves mc ON mc.asset_class = q.coll_class AND mc.side = 'collateral'
"""


def mark_positions(con):
    df = con.execute(MARK_SQL).df()
    df["required"] = df["loan_asof"] * df["haircut_req"]
    df["excess"] = df["coll_asof"] - df["required"]
    df["nonstandard"] = df["coll_class"].map(
        lambda c: ASSET_CLASSES[c]["nonstandard"])
    return df


def borrower_summary(con):
    """One row per borrower, the morning exposure report. A position whose
    borrower is not in reference data has nowhere to roll up to and drops
    out here, silently. That is why the loader checks for it first."""
    marks = mark_positions(con)
    bor = con.execute(
        'SELECT borrower_id, name, type, grade, "limit", nonstd_cap, buffer '
        "FROM borrowers").df()

    g = marks.groupby("borrower_id")
    out = pd.DataFrame({
        "on_loan": g["loan_asof"].sum(),
        "collateral": g["coll_asof"].sum(),
        "required": g["required"].sum(),
        "nonstd_collateral": marks[marks.nonstandard].groupby(
            "borrower_id")["coll_asof"].sum(),
    }).fillna({"nonstd_collateral": 0.0})
    out = bor.merge(out, left_on="borrower_id", right_index=True)

    out["coverage"] = out["collateral"] / out["on_loan"]
    out["required_coverage"] = out["required"] / out["on_loan"]
    out["excess"] = out["collateral"] - out["required"]
    out["margin_call"] = (-out["excess"]).clip(lower=0.0)
    out["utilization"] = out["on_loan"] / out["limit"]
    out["nonstd_share"] = out["nonstd_collateral"] / out["collateral"]
    out["status"] = out.apply(_status, axis=1)
    return out.sort_values("on_loan", ascending=False).reset_index(drop=True)


def _status(row):
    flags = []
    if row["margin_call"] > 0:
        flags.append("margin call")
    if row["utilization"] > 1.0:
        flags.append("over limit")
    elif row["utilization"] >= 0.9:
        flags.append("near limit")
    if row["nonstd_share"] > row["nonstd_cap"]:
        flags.append("non-standard cap breached")
    elif row["nonstd_share"] >= 0.9 * row["nonstd_cap"]:
        flags.append("non-standard near cap")
    return ", ".join(flags) if flags else "ok"


def book_totals(summary):
    calls = summary[summary.margin_call > 0]
    return {
        "on_loan": float(summary["on_loan"].sum()),
        "collateral": float(summary["collateral"].sum()),
        "coverage": float(summary["collateral"].sum() / summary["on_loan"].sum()),
        "n_margin_calls": int(len(calls)),
        "margin_call_total": float(calls["margin_call"].sum()),
        "n_limit_breaches": int((summary["utilization"] > 1.0).sum()),
        "n_nonstd_breaches": int(
            (summary["nonstd_share"] > summary["nonstd_cap"]).sum()),
    }

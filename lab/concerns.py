"""The data concern loop.

A data concern is a break in the feed that a consumer would otherwise
have met in a report. This module plants three of them, one at a time,
into a copy of the source frames: a position loaded twice, a position
keyed to a borrower that is not in reference data, and a price feed that
stopped updating. Each copy is loaded into a staging database and the
same checks the gated loader runs are run on it. A failed check is the
evidence. The exposure report is then recomputed on the broken copy and
compared with the clean one, borrower by borrower, so the impact on the
consumer is a number, not an adjective.

The breaks are planted, so the root cause is known. In the real loop the
root cause is what the analyst writes after tracing the break upstream;
here it is written next to the break so the record shows what a complete
concern looks like: what was caught, by which control, who is affected,
by how much, what protects them today, and what fixes it for good.
"""

from dataclasses import dataclass, field

import pandas as pd

from lab import exposure, generate
from lab.load import stage_frames
from lab.narrative import money

FROZEN_DAYS = 3
ORPHAN_ID = "B99"
SLA_DAYS = 10            # business days from raised to due


@dataclass
class Scenario:
    concern_id: str
    kind: str
    title: str
    affected_id: str
    caught_by: str
    expected_failures: set
    consumer: str
    root_cause: str
    compensating_action: str
    permanent_fix: str
    prices: pd.DataFrame = field(repr=False)
    borrowers: pd.DataFrame = field(repr=False)
    positions: pd.DataFrame = field(repr=False)


def _largest_position(positions, borrower_id):
    sub = positions[positions.borrower_id == borrower_id]
    return sub.sort_values("loan_prev", ascending=False).iloc[0]


def plant_breaks(seed=generate.SEED):
    prices = generate.generate_prices(seed)
    borrowers = generate.generate_borrowers()
    positions = generate.generate_positions(seed)

    # 1. the source sent one position twice (a rebooking that kept the
    # old row). Alder sits at 90% of its limit, so a duplicate tips it over
    dup = _largest_position(positions, "B01")
    pos_dup = pd.concat([positions, dup.to_frame().T], ignore_index=True)
    pos_dup = pos_dup.astype(positions.dtypes.to_dict())

    # 2. a position keyed to a borrower id that reference data does not
    # know. Dogwood is over its limit; losing its largest loan hides that
    orphan = _largest_position(positions, "B04")
    pos_orphan = positions.copy()
    pos_orphan.loc[pos_orphan.position_id == orphan.position_id,
                   "borrower_id"] = ORPHAN_ID

    # 3. the large cap lent price stopped updating: the last three closes
    # are the close before them, so today's rally never reaches the marks
    px_frozen = prices.copy()
    mask = (px_frozen.asset_class == "us_large_eq") & (px_frozen.side == "loan")
    series = px_frozen[mask].sort_values("date")
    stale = series["price"].iloc[-(FROZEN_DAYS + 1)]
    px_frozen.loc[series.index[-FROZEN_DAYS:], "price"] = stale

    return [
        Scenario(
            concern_id="DC-001", kind="duplicate",
            title="Position loaded twice from trade capture",
            affected_id=dup.position_id, caught_by="position_id_unique",
            expected_failures={
                "position_id_unique", "position_record_count",
                "on_loan_control_total", "on_loan_matches_config",
                "on_loan_by_borrower", "collateral_ties_to_requirement"},
            consumer="Exposure limit monitoring",
            root_cause="Amendment in trade capture wrote a new row and "
                       "kept the old one. The extract has no dedupe on "
                       "position id.",
            compensating_action="Exposure report for the day run on the "
                                "deduplicated staging copy, credit "
                                "officer told the limit flag is false.",
            permanent_fix="Extract keys on position id with the latest "
                          "version only. Loader rejects any id seen twice.",
            prices=prices, borrowers=borrowers, positions=pos_dup),
        Scenario(
            concern_id="DC-002", kind="orphan",
            title="Position keyed to a borrower not in reference data",
            affected_id=orphan.position_id,
            caught_by="positions_reference_borrower",
            expected_failures={
                "positions_reference_borrower", "on_loan_by_borrower",
                "collateral_ties_to_requirement"},
            consumer="Exposure limit monitoring, regulatory reporting",
            root_cause="Counterparty was re-papered under a new legal "
                       "entity id upstream. Reference data was not "
                       "updated, so the loan rolls up to nobody.",
            compensating_action="Loan mapped back to the parent by hand "
                                "for today's report. Limit breach "
                                "re-raised with the credit officer.",
            permanent_fix="Reference data change feeds the loader before "
                          "trade capture. Unmapped ids block the load.",
            prices=prices, borrowers=borrowers, positions=pos_orphan),
        Scenario(
            concern_id="DC-003", kind="frozen",
            title="Large cap lent price feed stopped updating",
            affected_id="us_large_eq", caught_by="price_feed_not_frozen",
            expected_failures={"price_feed_not_frozen"},
            consumer="Margin calls, exposure limit monitoring",
            root_cause="Vendor file for the equity basket failed to "
                       "refresh. The loader carried the prior close "
                       "forward with no flag.",
            compensating_action="Marks rerun with the vendor's resent "
                                "file. Calls that were missed go out "
                                "this afternoon.",
            permanent_fix="A traded series repeating its close three "
                          "days running fails the load.",
            prices=px_frozen, borrowers=borrowers, positions=positions),
    ]


def stage(scenario):
    """Load the broken copy ungated and run the checks against what the
    source says it sent. Returns the connection and every result."""
    expected = generate.control_totals(
        generate.generate_prices(), generate.generate_borrowers(),
        generate.generate_positions())
    return stage_frames(scenario.prices, scenario.borrowers,
                        scenario.positions, expected)


def impact(scenario, broken_con, clean_summary):
    """What the broken feed would have done to the exposure report, on
    the borrower it moved the most."""
    broken = exposure.borrower_summary(broken_con).set_index("borrower_id")
    clean = clean_summary.set_index("borrower_id")
    both = clean.join(broken, rsuffix="_b", how="left")
    both["on_loan_delta"] = both["on_loan_b"].fillna(0.0) - both["on_loan"]
    both["margin_call_delta"] = (both["margin_call_b"].fillna(0.0)
                                 - both["margin_call"])
    both["moved"] = both["on_loan_delta"].abs() + both["margin_call_delta"].abs()
    affected = both[both["moved"] > 0.5]
    worst = affected.sort_values("moved", ascending=False).iloc[0]
    name = worst["name"]
    n = len(affected)

    breach_masked = worst["utilization"] > 1.0 and worst["utilization_b"] <= 1.0
    false_breach = worst["utilization"] <= 1.0 and worst["utilization_b"] > 1.0

    if scenario.kind == "frozen":
        text = (f"{name} margin call of {money(-worst['margin_call_delta'])} "
                f"not raised, {n} borrowers mismarked")
    elif worst["on_loan_delta"] < 0:
        text = f"{name} on loan understated by {money(-worst['on_loan_delta'])}"
        if breach_masked:
            text += ", limit breach hidden"
    else:
        text = f"{name} on loan overstated by {money(worst['on_loan_delta'])}"
        if false_breach:
            text += ", false limit breach"

    if worst["margin_call_delta"] < -0.5 or worst["on_loan_delta"] < -0.5 \
            or breach_masked:
        severity = "high"        # risk understated: the expensive failure
    elif worst["on_loan_delta"] > 0.5:
        severity = "medium"      # risk overstated: good trades blocked
    else:
        severity = "low"

    return {
        "borrower": name,
        "n_borrowers_affected": n,
        "on_loan_clean": float(worst["on_loan"]),
        "on_loan_broken": float(worst["on_loan_b"]) if pd.notna(worst["on_loan_b"]) else 0.0,
        "margin_call_clean": float(worst["margin_call"]),
        "margin_call_broken": float(worst["margin_call_b"]) if pd.notna(worst["margin_call_b"]) else 0.0,
        "utilization_clean": float(worst["utilization"]),
        "utilization_broken": float(worst["utilization_b"]) if pd.notna(worst["utilization_b"]) else 0.0,
        "on_loan_delta": float(worst["on_loan_delta"]),
        "margin_call_delta": float(worst["margin_call_delta"]),
        "impact": text,
        "severity": severity,
    }


def unexplained(results, scenarios):
    """Failed checks that no planted break accounts for. Each becomes a
    concern with no root cause yet, which is what a real one looks like
    on the day it is raised."""
    known = set()
    for s in scenarios:
        known |= s.expected_failures
    rows = []
    for i, r in enumerate(results, 1):
        if r.passed or r.name in known:
            continue
        rows.append({
            "concern_id": f"DC-9{i:02d}", "title": f"Check failed: {r.name}",
            "caught_by": r.name, "detail": r.detail, "consumer": "unknown",
            "borrower": "", "impact": "not yet measured", "severity": "high",
            "root_cause": "not yet traced", "compensating_action": "none yet",
            "permanent_fix": "none yet", "status": "open"})
    return rows


def run(clean_con):
    """The concern log: one row per planted break."""
    as_of, _ = _dates(clean_con)
    clean_summary = exposure.borrower_summary(clean_con)
    rows = []
    for s in plant_breaks():
        con, results = stage(s)
        failed = [r for r in results if not r.passed]
        imp = impact(s, con, clean_summary)
        con.close()
        rows.append({
            "concern_id": s.concern_id,
            "raised": as_of,
            "due": as_of + pd.offsets.BDay(SLA_DAYS),
            "title": s.title,
            "caught_by": s.caught_by,
            "checks_failed": len(failed),
            "detail": next(r.detail for r in failed if r.name == s.caught_by),
            "consumer": s.consumer,
            **imp,
            "root_cause": s.root_cause,
            "compensating_action": s.compensating_action,
            "permanent_fix": s.permanent_fix,
            "status": "open",
        })
    return pd.DataFrame(rows)


def _dates(con):
    rows = con.execute(
        "SELECT DISTINCT date FROM prices ORDER BY date DESC LIMIT 2").fetchall()
    return pd.Timestamp(rows[0][0]), pd.Timestamp(rows[1][0])

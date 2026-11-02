"""Validation gates that run at every load.

Four families:
  record counts   - every row the source wrote is in the table
  control totals  - on loan per borrower and collateral per borrower in
                    the database match the figures computed at source,
                    and the book total matches the static config
  completeness    - no nulls, no negative values, no price at or below
                    zero, every series present on every date, no series
                    frozen on a repeated close
  reference data  - every position keys to a known borrower, every class
                    is a known class, every borrower has positions and a
                    limit, no position id appears twice

Every check returns a CheckResult. The loader blocks if any failed.
"""

from dataclasses import dataclass

from lab.book import BORROWERS, COLLATERAL_CLASSES, LOAN_CLASSES, total_on_loan

TOL = 1e-6

FAMILY = {
    "price_record_count": "record counts",
    "position_record_count": "record counts",
    "borrower_record_count": "record counts",
    "price_day_count": "record counts",
    "on_loan_control_total": "control totals",
    "on_loan_matches_config": "control totals",
    "on_loan_by_borrower": "control totals",
    "collateral_ties_to_requirement": "control totals",
    "position_nulls": "completeness",
    "position_negatives": "completeness",
    "price_positive": "completeness",
    "price_series_complete": "completeness",
    "price_jump_sanity": "completeness",
    "price_feed_not_frozen": "completeness",
    "position_id_unique": "reference data",
    "positions_reference_borrower": "reference data",
    "loan_classes_known": "reference data",
    "collateral_classes_known": "reference data",
    "every_borrower_has_positions": "reference data",
    "every_borrower_has_limit": "reference data",
}


class ValidationError(Exception):
    pass


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str

    @property
    def family(self):
        return FAMILY.get(self.name, "other")


def _check(name, passed, detail):
    return CheckResult(name=name, passed=bool(passed), detail=detail)


def run_checks(con, expected):
    results = []

    # record counts
    n_prices = con.execute("SELECT count(*) FROM prices").fetchone()[0]
    results.append(_check(
        "price_record_count", n_prices == expected["n_prices"],
        f"db has {n_prices}, source wrote {expected['n_prices']}"))

    n_pos = con.execute("SELECT count(*) FROM positions").fetchone()[0]
    results.append(_check(
        "position_record_count", n_pos == expected["n_positions"],
        f"db has {n_pos}, source wrote {expected['n_positions']}"))

    n_bor = con.execute("SELECT count(*) FROM borrowers").fetchone()[0]
    results.append(_check(
        "borrower_record_count", n_bor == len(BORROWERS),
        f"db has {n_bor}, config has {len(BORROWERS)}"))

    n_dates = con.execute("SELECT count(DISTINCT date) FROM prices").fetchone()[0]
    results.append(_check(
        "price_day_count", n_dates == expected["n_dates"] and n_dates >= 700,
        f"{n_dates} distinct dates"))

    # control totals
    on_loan = con.execute("SELECT sum(loan_prev) FROM positions").fetchone()[0]
    results.append(_check(
        "on_loan_control_total", abs(on_loan - expected["on_loan_total"]) < TOL,
        f"db {on_loan:.6f} vs source {expected['on_loan_total']:.6f}"))
    results.append(_check(
        "on_loan_matches_config", abs(on_loan - total_on_loan()) < 1e-3,
        f"db {on_loan:.3f} vs config {total_on_loan()}"))

    by_b = dict(con.execute(
        "SELECT borrower_id, sum(loan_prev) FROM positions GROUP BY 1").fetchall())
    gaps = {k: by_b.get(k, 0.0) - v
            for k, v in expected["on_loan_by_borrower"].items()}
    worst_k = max(gaps, key=lambda k: abs(gaps[k]))
    results.append(_check(
        "on_loan_by_borrower", abs(gaps[worst_k]) < TOL,
        f"largest gap to source {gaps[worst_k]:+.3f} on {worst_k}"))

    coll_b = dict(con.execute(
        "SELECT borrower_id, sum(coll_prev) FROM positions GROUP BY 1").fetchall())
    gaps = {k: coll_b.get(k, 0.0) - v
            for k, v in expected["coll_by_borrower"].items()}
    worst_k = max(gaps, key=lambda k: abs(gaps[k]))
    results.append(_check(
        "collateral_ties_to_requirement", abs(gaps[worst_k]) < TOL,
        f"collateral vs loan x requirement x (1 + buffer), largest gap "
        f"{gaps[worst_k]:+.3f} on {worst_k}"))

    # completeness
    nulls = con.execute("""
        SELECT count(*) FROM positions
        WHERE loan_prev IS NULL OR coll_prev IS NULL OR loan_class IS NULL
           OR coll_class IS NULL OR borrower_id IS NULL
    """).fetchone()[0]
    results.append(_check("position_nulls", nulls == 0, f"{nulls} null rows"))

    neg = con.execute(
        "SELECT count(*) FROM positions WHERE loan_prev <= 0 OR coll_prev <= 0"
    ).fetchone()[0]
    results.append(_check("position_negatives", neg == 0,
                          f"{neg} non-positive values"))

    bad_px = con.execute(
        "SELECT count(*) FROM prices WHERE price IS NULL OR price <= 0"
    ).fetchone()[0]
    results.append(_check("price_positive", bad_px == 0,
                          f"{bad_px} null or non-positive prices"))

    gaps = con.execute("""
        SELECT count(*) FROM (
            SELECT date, count(*) AS n FROM prices GROUP BY date
        ) WHERE n <> ?
    """, [expected["n_series"]]).fetchone()[0]
    results.append(_check("price_series_complete", gaps == 0,
                          f"{gaps} dates missing at least one series"))

    # a 40% move in one day in any class is a data error, not a market
    jumps = con.execute("""
        SELECT count(*) FROM (
            SELECT price / lag(price) OVER (
                PARTITION BY asset_class, side ORDER BY date) AS ratio
            FROM prices
        ) WHERE ratio > 1.4 OR ratio < 0.6
    """).fetchone()[0]
    results.append(_check("price_jump_sanity", jumps == 0,
                          f"{jumps} one-day moves beyond 40%"))

    # a traded series printing the same close three days running is a
    # feed that stopped updating, not a quiet market. cash is exempt
    frozen = con.execute("""
        SELECT asset_class, side, count(*) AS days FROM (
            SELECT asset_class, side, price,
                   lag(price, 1) OVER w AS p1, lag(price, 2) OVER w AS p2
            FROM prices WHERE asset_class <> 'cash'
            WINDOW w AS (PARTITION BY asset_class, side ORDER BY date)
        ) WHERE price = p1 AND price = p2
        GROUP BY 1, 2
    """).fetchall()
    results.append(_check(
        "price_feed_not_frozen", not frozen,
        ", ".join(f"{a} {s} repeated the prior close on {d} day(s)"
                  for a, s, d in frozen) if frozen else "no series frozen"))

    # reference data
    dupes = con.execute("""
        SELECT position_id FROM positions GROUP BY 1 HAVING count(*) > 1
    """).fetchall()
    results.append(_check(
        "position_id_unique", not dupes,
        f"{len(dupes)} position id(s) loaded more than once: "
        f"{', '.join(d[0] for d in dupes)}" if dupes else "all unique"))

    orphans = con.execute("""
        SELECT DISTINCT p.borrower_id FROM positions p
        LEFT JOIN borrowers b USING (borrower_id)
        WHERE b.borrower_id IS NULL
    """).fetchall()
    results.append(_check(
        "positions_reference_borrower", not orphans,
        f"positions keyed to borrower(s) not in reference data: "
        f"{', '.join(o[0] for o in orphans)}" if orphans
        else "every position keys to a known borrower"))

    classes = set(r[0] for r in con.execute(
        "SELECT DISTINCT loan_class FROM positions").fetchall())
    bad = classes - set(LOAN_CLASSES)
    results.append(_check("loan_classes_known", not bad,
                          f"unknown loan classes {sorted(bad)}" if bad else "all known"))
    classes = set(r[0] for r in con.execute(
        "SELECT DISTINCT coll_class FROM positions").fetchall())
    bad = classes - set(COLLATERAL_CLASSES)
    results.append(_check("collateral_classes_known", not bad,
                          f"unknown collateral classes {sorted(bad)}" if bad else "all known"))

    orphan = con.execute("""
        SELECT count(*) FROM borrowers b
        LEFT JOIN positions p USING (borrower_id)
        WHERE p.position_id IS NULL
    """).fetchone()[0]
    results.append(_check("every_borrower_has_positions", orphan == 0,
                          f"{orphan} borrowers with no positions"))

    no_limit = con.execute(
        "SELECT count(*) FROM borrowers WHERE \"limit\" IS NULL OR \"limit\" <= 0"
    ).fetchone()[0]
    results.append(_check("every_borrower_has_limit", no_limit == 0,
                          f"{no_limit} borrowers without a limit"))

    return results

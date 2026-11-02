"""Load the synthetic book into DuckDB and gate the load on validation.

Nothing downstream (exposure monitor, concern log, dashboard) reads the
raw frames. It all comes out of the database, and the database only
exists if every validation check passed.
"""

import duckdb

from lab import generate
from lab.validate import run_checks, ValidationError


def stage_frames(prices, borrowers, positions, expected, path=":memory:"):
    """Load three frames into a fresh database and run the checks. Does
    not block: returns the connection and every check result, which is
    what the concern log needs to show what a broken feed looks like."""
    con = duckdb.connect(path)
    con.register("prices_src", prices)
    con.register("borrowers_src", borrowers)
    con.register("positions_src", positions)
    con.execute("CREATE OR REPLACE TABLE prices AS SELECT * FROM prices_src")
    con.execute("CREATE OR REPLACE TABLE borrowers AS SELECT * FROM borrowers_src")
    con.execute("CREATE OR REPLACE TABLE positions AS SELECT * FROM positions_src")
    # drop the pandas-backed views once the tables exist. the connection
    # outlives this function (the app caches it) and a view that still
    # points at a collected frame is a native crash on reload
    for view in ("prices_src", "borrowers_src", "positions_src"):
        con.unregister(view)
    return con, run_checks(con, expected)


def build_db(path=":memory:", seed=generate.SEED):
    """The gated load. Any failed check closes the connection and raises,
    naming every check that failed."""
    prices = generate.generate_prices(seed)
    borrowers = generate.generate_borrowers()
    positions = generate.generate_positions(seed)
    expected = generate.control_totals(prices, borrowers, positions)
    con, results = stage_frames(prices, borrowers, positions, expected, path)
    failed = [r for r in results if not r.passed]
    if failed:
        con.close()
        lines = ". ".join(f"{r.name}: {r.detail}" for r in failed)
        raise ValidationError(
            f"load blocked, {len(failed)} check(s) failed: {lines}")
    return con, results


def as_of_dates(con):
    """The as-of date and the close before it."""
    rows = con.execute(
        "SELECT DISTINCT date FROM prices ORDER BY date DESC LIMIT 2").fetchall()
    return rows[0][0], rows[1][0]

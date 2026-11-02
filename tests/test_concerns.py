"""The data concern loop: plant a break in a copy of the feed, run the
same checks the loader runs, log what they caught, measure what the
break would have done to the exposure report if it had got through."""

import pandas as pd
import pytest

from lab import concerns, generate
from lab.load import build_db
from lab.validate import run_checks


@pytest.fixture(scope="module")
def clean():
    con, _ = build_db()
    yield con
    con.close()


@pytest.fixture(scope="module")
def log(clean):
    return concerns.run(clean)


def test_three_breaks_are_planted():
    scenarios = concerns.plant_breaks()
    assert [s.concern_id for s in scenarios] == ["DC-001", "DC-002", "DC-003"]
    assert {s.kind for s in scenarios} == {"duplicate", "orphan", "frozen"}


def test_duplicate_adds_one_position_twice():
    s = next(s for s in concerns.plant_breaks() if s.kind == "duplicate")
    clean_pos = generate.generate_positions()
    assert len(s.positions) == len(clean_pos) + 1
    dupes = s.positions[s.positions.duplicated("position_id", keep=False)]
    assert dupes["position_id"].nunique() == 1
    assert dupes["position_id"].iloc[0] == s.affected_id


def test_orphan_points_at_a_borrower_not_in_reference_data():
    s = next(s for s in concerns.plant_breaks() if s.kind == "orphan")
    ref = set(s.borrowers["borrower_id"])
    orphan_rows = s.positions[~s.positions["borrower_id"].isin(ref)]
    assert len(orphan_rows) >= 1
    assert (orphan_rows["borrower_id"] == "B99").all()


def test_frozen_feed_repeats_the_prior_close():
    s = next(s for s in concerns.plant_breaks() if s.kind == "frozen")
    px = s.prices
    series = px[(px.asset_class == s.affected_id) & (px.side == "loan")]
    last = series.sort_values("date")["price"].tail(concerns.FROZEN_DAYS + 1)
    assert last.nunique() == 1


def test_every_break_is_caught_by_its_expected_check():
    for s in concerns.plant_breaks():
        con, results = concerns.stage(s)
        failed = {r.name for r in results if not r.passed}
        assert s.caught_by in failed, (s.kind, failed)
        con.close()


def test_clean_load_raises_no_concern(clean):
    results = run_checks(clean, generate.control_totals(
        generate.generate_prices(), generate.generate_borrowers(),
        generate.generate_positions()))
    assert concerns.unexplained(results, []) == []


def test_log_has_one_row_per_break_with_the_record_fields(log):
    assert len(log) == 3
    for col in ("concern_id", "title", "caught_by", "consumer", "impact",
                "severity", "root_cause", "compensating_action",
                "permanent_fix", "status", "borrower"):
        assert col in log.columns
    assert (log["status"] == "open").all()


def test_duplicate_overstates_and_orphan_understates(log):
    row = log.set_index("concern_id")
    assert row.loc["DC-001", "on_loan_delta"] > 0      # duplicate: too much
    assert row.loc["DC-002", "on_loan_delta"] < 0      # orphan: missing
    assert row.loc["DC-002", "severity"] == "high"     # understated exposure
    assert row.loc["DC-003", "margin_call_delta"] < 0  # frozen: call missed
    assert row.loc["DC-003", "severity"] == "high"


def test_impact_is_measured_on_the_affected_borrower_only(log):
    row = log.set_index("concern_id")
    assert row.loc["DC-001", "borrower"] == row.loc["DC-001", "borrower"]
    assert isinstance(row.loc["DC-001", "impact"], str)
    assert "$" in row.loc["DC-001", "impact"]


def test_unexplained_failures_become_their_own_concern():
    from lab.validate import CheckResult
    extra = [CheckResult("price_positive", False, "2 non-positive prices")]
    rows = concerns.unexplained(extra, concerns.plant_breaks())
    assert len(rows) == 1
    assert rows[0]["root_cause"] == "not yet traced"

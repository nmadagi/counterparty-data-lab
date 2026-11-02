import numpy as np
import pytest

from lab import book, exposure
from lab.load import build_db


@pytest.fixture(scope="module")
def con():
    c, _ = build_db()
    yield c
    c.close()


def test_marks_apply_the_as_of_move(con):
    marks = exposure.mark_positions(con)
    # cash never moves, so cash collateral is unchanged from the prior close
    cash = marks[marks.coll_class == "cash"]
    assert np.allclose(cash["coll_asof"], cash["coll_prev"])
    # the as-of day is a rally, so lent equities are worth more
    eq = marks[marks.loan_class == "us_large_eq"]
    assert (eq["loan_asof"] > eq["loan_prev"]).all()


def test_summary_covers_every_borrower(con):
    s = exposure.borrower_summary(con)
    assert set(s["borrower_id"]) == set(book.BORROWERS)
    assert (s["on_loan"] > 0).all()
    assert (s["coverage"] > 1.0).all()


def test_margin_call_is_shortfall_against_requirement(con):
    s = exposure.borrower_summary(con)
    called = s[s.margin_call > 0]
    assert len(called) >= 1
    assert np.allclose(called["margin_call"], called["required"] - called["collateral"])
    assert (s.loc[s.margin_call == 0, "excess"] >= 0).all()


def test_status_flags(con):
    s = exposure.borrower_summary(con).set_index("name")
    assert "over limit" in s.loc["Dogwood", "status"]
    assert "non-standard cap breached" in s.loc["Dogwood", "status"]
    assert s.loc["Larch", "status"] == "ok"


def test_book_totals_reconcile(con):
    s = exposure.borrower_summary(con)
    t = exposure.book_totals(s)
    assert abs(t["on_loan"] - s["on_loan"].sum()) < 1e-6
    assert t["n_margin_calls"] == int((s.margin_call > 0).sum())
    assert t["margin_call_total"] == pytest.approx(s["margin_call"].sum())

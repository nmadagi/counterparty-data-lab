"""Export the validated tables and the engine outputs as CSV.

    python -m data.export [out_dir]

Writes prices, borrowers, positions (the inputs), the marked positions,
the borrower exposure report and the concern log (the outputs), plus a
column dictionary.
"""

import os
import sys

from lab import concerns, exposure, report
from lab.load import build_db

DICTIONARY = """column dictionary

prices.csv: one row per date, asset class and side. side is loan (the
basket lent out) or collateral (the basket received). price starts at
100 on the first day. cash is always 100.

borrowers.csv: one row per borrower, the reference data. limit is the
maximum on loan in USD millions. nonstd_cap is the share of collateral
allowed to be non-standard (equities, high yield). buffer is the extra
collateral the borrower habitually keeps above the requirement.

positions.csv: one row per loan, the trade capture feed. loan_prev and
coll_prev are USD millions at the previous close. haircut_req is the
house margin requirement for that collateral class.

marked_positions.csv: positions.csv with the as-of day's prices applied.
loan_asof and coll_asof are USD millions at the as-of close, required
is loan_asof times haircut_req, excess is coll_asof minus required.

exposure_report.csv: one row per borrower at the as-of close, the
morning report on the exposure tab. Money in USD millions.

concern_log.csv: one row per data concern. caught_by is the load check
that failed, detail is what it reported, borrower and impact are the
consumer most affected and by how much, on_loan_delta and
margin_call_delta are USD millions (broken minus clean), severity is
high when risk would have been understated.
"""


def main(out_dir="data"):
    con, _ = build_db()
    os.makedirs(out_dir, exist_ok=True)
    for table in ("prices", "borrowers", "positions"):
        con.execute(f"SELECT * FROM {table}").df().to_csv(
            os.path.join(out_dir, f"{table}.csv"), index=False)
    exposure.mark_positions(con).to_csv(
        os.path.join(out_dir, "marked_positions.csv"), index=False)
    exposure.borrower_summary(con).to_csv(
        os.path.join(out_dir, "exposure_report.csv"), index=False)
    with open(os.path.join(out_dir, "concern_log.csv"), "wb") as f:
        f.write(report.concerns_csv(concerns.run(con)))
    with open(os.path.join(out_dir, "README.txt"), "w") as f:
        f.write(DICTIONARY)
    con.close()
    print(f"wrote 6 csv files and a column dictionary to {out_dir}/")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data")

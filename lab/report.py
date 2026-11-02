"""Exports: the morning exposure report and the concern log as CSV.
Plain on purpose; these are what a consumer or an auditor would ask
for."""

EXPOSURE_COLUMNS = [
    "borrower_id", "name", "type", "grade", "on_loan", "collateral",
    "coverage", "required_coverage", "excess", "margin_call", "limit",
    "utilization", "nonstd_share", "nonstd_cap", "status"]

CONCERN_COLUMNS = [
    "concern_id", "raised", "due", "status", "severity", "title",
    "caught_by", "detail", "consumer", "borrower", "impact",
    "on_loan_delta", "margin_call_delta", "root_cause",
    "compensating_action", "permanent_fix"]


def exposure_csv(summary):
    return summary[EXPOSURE_COLUMNS].to_csv(index=False).encode()


def concerns_csv(log):
    out = log[CONCERN_COLUMNS].copy()
    for c in ("raised", "due"):
        out[c] = out[c].dt.strftime("%Y-%m-%d")
    return out.to_csv(index=False).encode()

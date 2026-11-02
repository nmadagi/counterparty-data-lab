"""Counterparty data lab - Streamlit front end.

Three tabs: data controls, data concerns, counterparty exposure. Every
number comes out of the validated DuckDB layer. The UI only formats.
"""

import json
import os
import tomllib

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lab import concerns, exposure, narrative, report
from lab.load import as_of_dates, build_db

st.set_page_config(page_title="counterparty data lab", layout="wide")

ACCENT = "#1f5c8b"
RED = "#b03a2e"
DARK = "#2c3e50"
AMBER = "#e67e22"
FAMILIES = ["record counts", "control totals", "completeness", "reference data"]


def usd(x):
    # engine values are USD millions; show billions past 1,000
    sign = "-" if x < 0 else ""
    a = abs(x)
    if a >= 1000:
        return f"{sign}${a / 1000:,.2f}B"
    return f"{sign}${a:,.0f}M"


def bn(x):
    """millions -> billions for chart axes."""
    return x / 1000


def esc(text):
    # streamlit reads $...$ in markdown as latex
    return text.replace("$", "\\$")


def card(col, title, value, note=None, alert=False):
    """A metric with a plain note under it. st.metric's delta draws an up
    arrow, which reads as "up since yesterday" on a label that is not a
    change at all, so the note is a caption instead."""
    col.metric(title, value)
    if note:
        col.caption(f":red[{esc(note)}]" if alert else esc(note))


@st.cache_resource
def get_db():
    con, results = build_db()
    return con, results


@st.cache_data
def run_concerns(_con):
    return concerns.run(_con)


@st.cache_data(show_spinner="drafting the summary")
def make_narrative(payload_json, api_key):
    return narrative.generate(json.loads(payload_json), api_key)


# one cached database, but a duckdb connection is not safe to share
# between threads and streamlit runs every browser session in its own.
# a cursor is a cheap per-session connection onto the same in-memory db.
_base_con, check_results = get_db()
con = _base_con.cursor()
as_of, prev_close = as_of_dates(con)

st.title("Counterparty data lab")
st.caption(
    "Synthetic securities lending book, twelve borrowers, charts in USD "
    "billions. All data is generated: no real institution, no real "
    "client, no real price. Built to show the data layer under a "
    "counterparty exposure number: the controls that gate the load, the "
    "concerns raised when a feed breaks, and what each break would have "
    "done to the report.")
passed = sum(1 for r in check_results if r.passed)
st.caption(f"This load: {passed}/{len(check_results)} data controls passed. "
           f"As of {as_of.strftime('%d %b %Y')} close.")

summary = exposure.borrower_summary(con)
totals = exposure.book_totals(summary)
log = run_concerns(con)

tab_ctl, tab_dc, tab_exp = st.tabs([
    "Data controls", "Data concerns", "Counterparty exposure"])


# ------------------------------------------------------------ controls
with tab_ctl:
    n_rows = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
              for t in ("positions", "prices", "borrowers")}
    c1, c2, c3, c4 = st.columns(4)
    card(c1, "Controls passed", f"{passed} of {len(check_results)}",
         "any failure blocks the load")
    card(c2, "Positions loaded", f"{n_rows['positions']:,}",
         f"{n_rows['borrowers']} borrowers in reference data")
    card(c3, "Prices loaded", f"{n_rows['prices']:,}",
         "12 series, three years of closes")
    card(c4, "On loan ties to source", usd(totals["on_loan"]),
         "control total matched at every load")

    st.subheader("Every check on this load")
    rows = pd.DataFrame({
        "Family": [r.family for r in check_results],
        "Check": [r.name for r in check_results],
        "Result": ["pass" if r.passed else "FAIL" for r in check_results],
        "What it found": [r.detail for r in check_results],
    })
    rows["order"] = rows["Family"].map(FAMILIES.index)
    rows = rows.sort_values(["order", "Check"]).drop(columns="order")
    st.dataframe(rows, hide_index=True, use_container_width=True,
                 column_config={
                     "What it found": st.column_config.TextColumn(width="large")})
    st.caption(
        "Record counts: every row the source sent is in the table. "
        "Control totals: on loan and collateral per borrower tie back to "
        "what the source computed. Completeness: no nulls, no negative or "
        "zero prices, every series on every date, no series frozen on a "
        "repeated close. Reference data: every position keys to a known "
        "borrower and a known asset class, no position id twice. A failed "
        "check names itself and the load stops. Nothing downstream ever "
        "reads the raw feed.")


# ------------------------------------------------------------ concerns
with tab_dc:
    high = log[log.severity == "high"]
    at_stake = (log["on_loan_delta"].abs() + log["margin_call_delta"].abs()).sum()
    c1, c2, c3, c4 = st.columns(4)
    card(c1, "Open concerns", f"{len(log)}", "all raised on this feed")
    card(c2, "High severity", f"{len(high)}",
         "risk would have been understated", alert=len(high) > 0)
    card(c3, "Exposure misstated", usd(at_stake),
         "across the borrowers each break moved most")
    card(c4, "Remediation due", log["due"].max().strftime("%d %b %Y"),
         f"{concerns.SLA_DAYS} business days from raised")

    st.subheader("Concern log")
    table = pd.DataFrame({
        "ID": log["concern_id"],
        "Severity": log["severity"],
        "Concern": log["title"],
        "Caught by": log["caught_by"],
        "Consumer": log["consumer"],
        "Impact if it had loaded": log["impact"],
        "Raised": log["raised"].dt.strftime("%d %b"),
        "Due": log["due"].dt.strftime("%d %b"),
        "Status": log["status"],
    })
    st.dataframe(table, hide_index=True, use_container_width=True,
                 column_config={
                     "Concern": st.column_config.TextColumn(width="medium"),
                     "Impact if it had loaded":
                         st.column_config.TextColumn(width="large")})
    st.caption(
        "Each concern is one break planted in a copy of the source feed, "
        "loaded into a staging database and run through the same checks "
        "as the live load. The check that fails is the evidence. The "
        "exposure report is then recomputed on the broken copy and "
        "compared with the clean one, so the impact on the consumer is a "
        "number. High severity means the break would have understated "
        "risk: a hidden limit breach or a margin call not raised. Medium "
        "means overstated: good business blocked. The breaks are planted, "
        "so the root cause is known. On a real feed that line is what the "
        "analyst writes after tracing the break upstream.")

    st.subheader("One concern, end to end")
    pick = st.selectbox("Concern", list(log["concern_id"]),
                        format_func=lambda i: f"{i}: "
                        f"{log.set_index('concern_id').loc[i, 'title']}")
    c = log.set_index("concern_id").loc[pick]
    left, right = st.columns([3, 2])
    with left:
        st.write(f"**Evidence.** Check `{c['caught_by']}` reported: "
                 f"{esc(c['detail'])}. {c['checks_failed']} of "
                 f"{len(check_results)} checks failed on the staging load. "
                 "This is the one that names the cause.")
        st.write(f"**Consumer affected.** {c['consumer']}.")
        st.write(f"**Impact.** {esc(c['impact'])}.")
        st.write(f"**Root cause.** {c['root_cause']}")
        st.write(f"**Compensating action today.** {c['compensating_action']}")
        st.write(f"**Permanent fix.** {c['permanent_fix']}")
        st.write(f"**Status.** {c['status']}, raised "
                 f"{c['raised'].strftime('%d %b %Y')}, due "
                 f"{c['due'].strftime('%d %b %Y')}.")
    with right:
        st.write(f"**{c['borrower']}, clean load against broken load**")
        side = pd.DataFrame({
            "": ["On loan", "Margin call", "Limit used"],
            "Clean": [usd(c["on_loan_clean"]), usd(c["margin_call_clean"]),
                      f"{c['utilization_clean']:.0%}"],
            "Broken": [usd(c["on_loan_broken"]), usd(c["margin_call_broken"]),
                       f"{c['utilization_broken']:.0%}"],
        })
        st.dataframe(side, hide_index=True, use_container_width=True)
        st.caption(f"The borrower this break moved most. "
                   f"{c['n_borrowers_affected']} borrower(s) moved in all.")
    st.download_button("Download concern log (CSV)",
                       report.concerns_csv(log),
                       file_name=f"concerns_{as_of.strftime('%Y%m%d')}.csv")


# ------------------------------------------------------------ exposure
with tab_exp:
    c1, c2, c3, c4 = st.columns(4)
    card(c1, "On loan", usd(totals["on_loan"]))
    card(c2, "Collateral held", usd(totals["collateral"]),
         f"{totals['coverage']:.1%} coverage")
    card(c3, "Margin calls this morning",
         f"{totals['n_margin_calls']} borrowers",
         f"{usd(totals['margin_call_total'])} to collect today",
         alert=totals["n_margin_calls"] > 0)
    card(c4, "Limit and cap breaches",
         f"{totals['n_limit_breaches'] + totals['n_nonstd_breaches']}",
         f"{totals['n_limit_breaches']} exposure limit, "
         f"{totals['n_nonstd_breaches']} non-standard collateral cap")

    st.subheader("On loan against exposure limit, by borrower")
    plot = summary.sort_values("on_loan")

    def _color(status):
        if status == "ok":
            return ACCENT
        if status.replace("near limit", "").replace(
                "non-standard near cap", "").strip(", ") == "":
            return AMBER
        return RED
    colors = [_color(s) for s in plot["status"]]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=bn(plot["on_loan"]), y=plot["name"], orientation="h",
        marker_color=colors, showlegend=False,
        hovertemplate="%{y}: $%{x:.2f}B on loan<extra></extra>"))
    # the bar colour is the status, so the legend names the three statuses
    for status, color in [("clean", ACCENT), ("near a limit or cap", AMBER),
                          ("action today", RED)]:
        fig.add_trace(go.Bar(x=[None], y=[None], orientation="h",
                             marker_color=color, name=status))
    fig.add_trace(go.Scatter(x=[None], y=[None], mode="lines",
                             line=dict(color=DARK, width=2),
                             name="exposure limit"))
    # a marker symbol drifted off its row, so each limit is a line drawn
    # inside that borrower's own category slot
    for i, lim in enumerate(plot["limit"]):
        fig.add_shape(type="line", xref="x", yref="y", x0=bn(lim),
                      x1=bn(lim), y0=i - 0.42, y1=i + 0.42,
                      line=dict(color=DARK, width=2))
    xmax = bn(max(plot["limit"].max(), plot["on_loan"].max())) * 1.05
    fig.update_layout(height=440, barmode="overlay",
                      margin=dict(l=10, r=10, t=10, b=10),
                      xaxis=dict(title="USD billions", tickprefix="$",
                                 ticksuffix="B", range=[0, xmax]),
                      yaxis=dict(categoryorder="array",
                                 categoryarray=list(plot["name"])),
                      legend=dict(orientation="h", y=-0.18))
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Bar colour is today's status. Blue is clean. Amber is within "
               "10% of a limit or cap. Red needs a decision today: a margin "
               "call, a limit breach or too much non-standard collateral. "
               "The dark tick on each row is that borrower's exposure limit, and "
               "a bar past its tick is over the limit.")

    st.subheader("Morning exposure report")
    rep = summary
    table = pd.DataFrame({
        "Borrower": rep["name"] + " (" + rep["type"] + ", " + rep["grade"] + ")",
        "On loan": rep["on_loan"].map(usd),
        "Collateral": rep["collateral"].map(usd),
        "Coverage": rep["coverage"].map(lambda v: f"{v:.1%}"),
        "Required": rep["required_coverage"].map(lambda v: f"{v:.1%}"),
        "Excess / (call)": rep["excess"].map(
            lambda v: usd(v) if v >= 0 else f"({usd(-v)})"),
        "Limit used": rep["utilization"].map(lambda v: f"{v:.0%}"),
        "Non-standard": rep.apply(
            lambda r: f"{r['nonstd_share']:.0%} of {r['nonstd_cap']:.0%}",
            axis=1),
        "Status": rep["status"],
    })
    st.dataframe(table, hide_index=True, use_container_width=True,
                 column_config={
                     "Borrower": st.column_config.TextColumn(width="medium"),
                     "Status": st.column_config.TextColumn(width="large")})
    st.caption(
        "Required is the house margin schedule weighted across the "
        "borrower's collateral. Excess is what it holds above that after "
        "today's move, and a bracketed figure is the call going out. "
        "Non-standard is equities and high yield as collateral, against "
        "the cap for that credit grade.")
    st.download_button("Download exposure report (CSV)",
                       report.exposure_csv(summary),
                       file_name=f"exposure_{as_of.strftime('%Y%m%d')}.csv")

    st.subheader("Senior management summary")
    # streamlit prints a scary red box if you touch st.secrets with no
    # secrets.toml where it looks (working dir or home, not the app dir).
    # only call it when one of those exists; if the app was launched from
    # elsewhere, read the app-dir file directly.
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    st_paths = [os.path.join(os.getcwd(), ".streamlit", "secrets.toml"),
                os.path.expanduser("~/.streamlit/secrets.toml")]
    app_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            ".streamlit", "secrets.toml")
    if not api_key and any(os.path.exists(p) for p in st_paths):
        api_key = st.secrets.get("ANTHROPIC_API_KEY", None)
    elif not api_key and os.path.exists(app_path):
        with open(app_path, "rb") as f:
            api_key = tomllib.load(f).get("ANTHROPIC_API_KEY")
    payload = narrative.build_payload(summary, totals, log, check_results,
                                      pd.Timestamp(as_of))
    if os.environ.get("LAB_OFFLINE"):
        # tests and screenshots: the template, no network call at all
        text, source = narrative.template_narrative(payload), "template"
    else:
        text, source = make_narrative(json.dumps(payload), api_key)
    st.write(esc(text))
    st.caption(
        "Drafted by the LLM from computed figures only, then verified "
        "number-by-number against the engine output."
        if source == "llm" else
        "Deterministic template (no API key configured. The LLM path, "
        "when enabled, is verified number-by-number against the engine "
        "output).")

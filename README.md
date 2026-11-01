# collateral-haircut-lab

[![ci](https://github.com/nmadagi/collateral-haircut-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/nmadagi/collateral-haircut-lab/actions/workflows/ci.yml)

I built this to work out where the margin cushion in a securities
lending book actually sits. Agency lenders take 102% collateral against
cash and 105% against everything else, for every borrower and every
security, whatever the market is doing. That number is a convention. I
wanted to see what happens when you backtest it the way you would
backtest a VaR. It is a synthetic agency lending book: twelve
borrowers, four lent asset classes, five collateral classes, three years
of daily prices with a planted stress episode, marked every day against
the requirement and the limits. On this book the flat schedule is beaten
156 times where 55 would be expected at 99%, red on both equity-versus-
cash pairs and never once on Treasuries. Scaling the haircut to the
volatility of each pair brings the count to 54 and needs $205 million
less collateral. The cushion is in the wrong places, not too small.

All data is synthetic. No real institution, no real client, no real
price.

![dashboard](docs/dashboard.png)

Live app: https://collateral-haircut-lab.streamlit.app

## Run it

```
pip install -r requirements.txt
streamlit run app.py
```

Tests: `python -m pytest tests/`. Export the tables as CSV:
`python -m data.export`.

## How it hangs together

How the modules fit together (each box is one file):

```mermaid
flowchart TD

subgraph group_book["Synthetic Book"]
  node_book_config["Book configuration<br/>[book.py]"]
  node_generator["Book generator<br/>[generate.py]"]
end

subgraph group_foundation["Data Foundation"]
  node_loader["Validated loader<br/>[load.py]"]
  node_validator["Load checks<br/>[validate.py]"]
  node_duckdb[("Book database")]
end

subgraph group_engines["Risk Engines"]
  node_exposure["Exposure monitor<br/>[exposure.py]"]
  node_haircut["Haircut backtest<br/>[haircut.py]"]
  node_firedrill["Default fire drill<br/>[firedrill.py]"]
end

subgraph group_outputs["Application and Outputs"]
  node_app["Streamlit dashboard<br/>[app.py]"]
  node_narrative["Summary narrative<br/>[narrative.py]"]
  node_report["CSV/PDF reports<br/>[report.py]"]
  node_export["CSV table export<br/>[export.py]"]
end

node_user(("Risk user"))
node_llm{{"Anthropic API"}}

node_user -->|"uses"| node_app
node_loader -->|"generates inputs"| node_generator
node_loader -->|"runs checks"| node_validator
node_generator -->|"uses configuration"| node_book_config
node_loader -->|"loads tables"| node_duckdb
node_validator -->|"checks tables"| node_duckdb
node_exposure -->|"reads SQL"| node_duckdb
node_haircut -->|"reads SQL"| node_duckdb
node_firedrill -->|"reads SQL"| node_duckdb
node_firedrill -->|"marks positions"| node_exposure
node_haircut -->|"marks positions"| node_exposure
node_app -->|"builds book"| node_loader
node_app -->|"shows monitoring"| node_exposure
node_app -->|"shows backtest"| node_haircut
node_app -->|"runs drill"| node_firedrill
node_app -->|"builds summary"| node_narrative
node_narrative -.->|"phrases figures"| node_llm
node_app -.->|"formats reports"| node_report
node_export -->|"builds book"| node_loader
node_export -->|"exports results"| node_exposure
node_export -->|"exports results"| node_haircut
node_export -->|"exports results"| node_firedrill

classDef toneBlue fill:#dbeafe,stroke:#2563eb,stroke-width:1.5px,color:#172554
classDef toneAmber fill:#fef3c7,stroke:#d97706,stroke-width:1.5px,color:#78350f
classDef toneMint fill:#dcfce7,stroke:#16a34a,stroke-width:1.5px,color:#14532d
classDef toneRose fill:#ffe4e6,stroke:#e11d48,stroke-width:1.5px,color:#881337
class node_book_config,node_generator,node_user toneBlue
class node_loader,node_validator,node_duckdb toneAmber
class node_exposure,node_haircut,node_firedrill,node_llm toneMint
class node_app,node_narrative,node_report,node_export toneRose
```

Prices, borrowers and position-level loans are generated with a fixed
seed and loaded into DuckDB. The load is gated: record counts, on-loan
control totals per borrower, collateral tied to loan times requirement
times buffer, price completeness across every series and every date.
Any failed check blocks the load and names itself. Everything downstream
reads from that layer with SQL.

Three tabs. The exposure monitor marks every position at the as-of
close, rolls it up per borrower against the flat requirement, and
flags the margin calls, the exposure limit breaches and the non-standard
collateral cap breaches for the morning. The haircut backtest puts the
flat schedule next to a volatility-scaled haircut (a 99% two-day move of
the lent basket over the collateral basket from the trailing year,
floored at 101%) for every pair in the book, counts exceedances after
the first year and zones them with the Basel traffic light. The fire
drill defaults one borrower and closes it out, either at today's prices
or over the worst two consecutive days in the history for that
borrower's mix, with netting under one master agreement.

The one AI piece is the senior management summary. The engine computes,
the LLM only phrases: it gets a block of finished figures, and every
number in its reply is checked against that block before display. If it
invents one, the reply is discarded for a deterministic template. No API
key means the template runs alone.

Calibration and every simplification are written up in
[docs/assumptions.md](docs/assumptions.md). Build decisions are in
[notes.md](notes.md).

## Author

Nitin Madagi - [github.com/nmadagi](https://github.com/nmadagi)

MIT license.

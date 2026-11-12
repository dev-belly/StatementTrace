# StatementTrace

[![CI](https://github.com/dev-belly/StatementTrace/actions/workflows/ci.yml/badge.svg)](https://github.com/dev-belly/StatementTrace/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-3776AB)
![Runtime](https://img.shields.io/badge/runtime-standard_library-128a82)
![Optional warehouse](https://img.shields.io/badge/optional-Polars_%2B_DuckDB_%2B_dbt-1d634b)

**From public filings to an inspectable financial research conclusion.**

**Profit grows. Does cash follow?** The new historical study compares Apple,
Microsoft and Alphabet across FY2023–FY2024 using 24 curated filing facts.
Alphabet's net income grew **35.67%**, while free cash flow grew **4.70%**;
the cash-flow bridge explains the difference in operating cash flow and cash capex.

[Read the research report](https://dev-belly.github.io/StatementTrace/cashflow/) ·
[中文研究简报](docs/CASHFLOW_STUDY.zh-CN.md) ·
[24 source facts](examples/cashflow/source_facts.csv) ·
[Python implementation](src/statementtrace/cashflow.py) ·
[SQL comparison](src/statementtrace/data/cashflow_compare.sql)

Historical filed-date cutoff: **2025-02-05**. The issuers' fiscal windows differ;
Apple's FY2023 has 53 weeks. Compare each issuer with its own prior year.
FCF here means CFO minus cash capex, excluding acquisitions and noncash additions.

```bash
python -m pip install -e .
statementtrace compare --out output/cashflow
statementtrace verify-comparison output/cashflow
python -m http.server 8000 --directory output/cashflow
```

Open `http://localhost:8000`. The self-contained report includes all six
issuer-years, signed cash-flow contributions, downloadable CSV, exact ratios,
the frozen source packet and the SQLite query. It works without JavaScript or
network access after installation. Add `--as-of 2025-02-04` to `compare` and use
a new output directory to see Alphabet become unavailable under the packet's
filed-date rule. The packet does not contain its earlier filings.

## Financial data engineering: Polars → Parquet → DuckDB → dbt

The same filing case also runs through a typed columnar pipeline. Polars lazily
normalizes selected facts into Zstd Parquet; DuckDB recomputes the annual cash-flow
mart; a three-model dbt project rebuilds it with source contracts and data tests.
Every route is checked against the Python result: **24 input slots, six issuer-years,
138 exact field comparisons per SQL route** in the default case.

| Tool | Implemented responsibility | Inspect |
| --- | --- | --- |
| Polars | Lazy NDJSON scan, explicit integer/date schema, typed missing slots | [Pipeline](src/statementtrace/warehouse.py) |
| Parquet + Zstd | Portable source and mart files; dates and exact amounts retained | [Packet format](docs/WAREHOUSE.zh-CN.md#产物与精度) |
| DuckDB | SQL pivot, window functions, adjacent-period bridge, exact ratio pairs | [SQL](src/statementtrace/data/warehouse_cashflow.sql) |
| dbt Core + dbt-duckdb | Staging contract, annual model, cash-flow mart and 21 data tests | [Models](warehouse_dbt/models) |
| uv + GitHub Actions | Locked dependencies; Linux/Windows and installed-wheel checks | [CI](.github/workflows/warehouse.yml) |

From this checkout, with [uv](https://docs.astral.sh/uv/) installed:

```bash
uv sync --locked --extra warehouse --extra dbt --extra dev
uv run --locked statementtrace warehouse --out output/warehouse
uv run --locked statementtrace verify-warehouse output/warehouse
uv run --locked python scripts/check_warehouse_dbt.py output/warehouse
```

The last command actually runs `dbt build`, compares its mart with Python and
checks that a single future-filed input fails the cutoff test. These are local
research workflows on a small curated packet, without a scale or speed claim.
The existing `demo` and `compare` commands still install with no runtime dependencies.
[中文运行与方法说明](docs/WAREHOUSE.zh-CN.md).

## Typed financial API: FastAPI + Pydantic + Uvicorn

Query a verified warehouse by issuer and fiscal period, then follow its selected
facts to their filings. The API captures and verifies one packet before serving;
every response identifies the same snapshot. Amounts use exact integer strings,
ratios use integer numerator/denominator pairs, and missing values remain `null`.

```bash
uv sync --locked --extra warehouse --extra api --extra dev
uv run --locked statementtrace warehouse --out output/api-demo
uv run --locked statementtrace serve-warehouse output/api-demo
```

Open `http://127.0.0.1:8000/docs` for Swagger UI, or query
`http://127.0.0.1:8000/v1/cashflow?symbol=GOOGL&period=2024`.
`/v1/facts` supports the same filters plus a source metric; both endpoints provide
bounded pagination. Unknown or duplicate parameters receive HTTP 422, including
an unsupported `as_of` override. Build a new packet and restart to change cutoffs.
The service exposes GET routes; no arbitrary SQL or file-upload interface is provided.

[中文 API 运行与精度说明](docs/API.zh-CN.md) ·
[Typed models and application factory](src/statementtrace/api.py) ·
[HTTP request examples](examples/api/requests.http) ·
[Real HTTP smoke](scripts/check_api.py)

## Filing-date analysis underneath the study

Which numbers were publicly filed by this cutoff, and which records produced this ratio? StatementTrace answers with a reproducible report from SEC CompanyFacts-shaped JSON. The offline demo uses **33 manually curated records from Apple's 2023/2024 Form 10-K tables**; it is not an unmodified API download.

**[Try the live financial report](https://dev-belly.github.io/StatementTrace/)**

**Try one cutoff change:** [FY2024 before filing](https://dev-belly.github.io/StatementTrace/#as_of=2024-10-31&period=2024) → [after filing](https://dev-belly.github.io/StatementTrace/#as_of=2024-11-01&period=2024). See missing financial inputs become available, then follow the selected facts to the source filing. No installation or account is needed.

**Demo snapshot · Apple FY2024**

SEC filed-date cutoff: **2024-11-01**. Values are in USD millions.

| Revenue | Net margin | Free cash flow |
| ---: | ---: | ---: |
| 391,035 | 23.97% | 108,807 |

33 curated records · 6 as-of panels · 9 metrics per panel.

Exact fiscal periods → selected facts → formulas → source filings.

Offline public-filing excerpt; missing values remain missing and lineage can be replayed.

## Quick start

```bash
git clone https://github.com/dev-belly/StatementTrace.git
cd StatementTrace
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
statementtrace demo --out output/demo
statementtrace verify output/demo
python -m http.server 8000 --directory output/demo
```

For **Windows PowerShell**, use the virtual environment directly; activation is optional:

```powershell
git clone https://github.com/dev-belly/StatementTrace.git
cd StatementTrace
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\statementtrace.exe demo --out output/demo
.\.venv\Scripts\statementtrace.exe verify output/demo
.\.venv\Scripts\python.exe -m http.server 8000 --directory output/demo
```

Open `http://localhost:8000`, choose a cutoff and fiscal year, inspect the formulas and follow selected facts to SEC filings. The committed report is in [examples/demo](examples/demo); GitHub displays HTML as source, so download or serve it locally.

## Share the exact financial view

Changing either selector updates the address with its cutoff and fiscal year.
Open or copy **Link to this view** to restore the same saved panel, including
with the browser's Back and Forward controls. The link identifies the view;
it does not upload a local report or fetch new SEC data. Public-page links can
be shared directly; local links require the same report copy.

For a short demonstration, compare the two FY2024 links above. At the October 31
cutoff, missing inputs remain missing. At the November 1 filed-date cutoff,
free cash flow is **USD 108,807 million**, from operating cash flow minus capex.
The source records are the same manually curated filing excerpt in both views.
This uses filed dates, without an intraday availability or investment claim.

Unknown, duplicate or malformed view parameters show a notice and the latest
configured panel. With JavaScript disabled, all six demo panels remain readable.
The report links to its method, GitHub project and author for further review.

## Download one view for review

Each panel has **Download these metrics · CSV**. It saves only that cutoff/year's
nine metric rows, including the formula, unit, status, exact fraction, rounded
display and missing-input names. Switching views or reopening a shared link
selects the matching panel's download. **All metrics CSV** still contains all
54 demo rows. Every panel's download also works with JavaScript disabled.

**Download selected facts · CSV** saves that panel's eleven selected-fact rows,
including explicit missing rows, integer USD values, exact period dates, filed
date, concept, accession, full fact ID and SEC source URL. Its rows and column
order match the same cutoff/year slice of **Facts CSV**. This is the panel's
selected facts, not every metric input: annual revenue growth can also use
prior-period revenue. Follow **Full lineage** with the complete report for that
input. Both downloads work offline and with JavaScript disabled.

Both filenames contain the cutoff and a safe period identifier, so downloads
for FY2023 and FY2024 at the same cutoff remain distinguishable. Special labels
retain their exact identity in the CSV, while the filename uses a short ASCII
label and a deterministic period digest.

For Excel, use **Data → From Text/CSV**, select UTF-8, and keep the `as_of`,
`period`, `exact`, `value_usd`, `accession` and `fact_id` columns as text
when present to preserve dates, identities, exact amounts and fractions.
The `display` column is rounded; `exact` retains the saved rational value.
The CSV uses the same text markers for formula-shaped labels as the full export.

Try the before/after-filing links above, downloading each view. FY2024 before
filing has nine `missing_input` rows with empty values. After filing,
`free_cash_flow` retains `108807000000/1`, unit `USD`, status `ok` and the
`operating_cash_flow - capex` formula. The selected-facts download keeps all
eleven `missing` rows before filing, then carries the available records and
their original source metadata after filing. These are filtered review exports;
full source/lineage review and semantic verification use the complete report.

## Contracts

| Concern | Behavior |
|---|---|
| Availability | `filed <= as_of`; later filings cannot leak into earlier snapshots |
| Fiscal periods | Exact start/end for duration facts; exact end for instant facts, including 53-week years |
| Comparatives | Match the reported period, rather than the filing's `fy` |
| Units / forms | Integral USD values, annual `10-K`/`10-K/A`; no implicit currency conversion |
| Ambiguity | Conflicting latest same-day facts or aliases fail closed |
| Missing data | Explicit missing-input and zero-denominator statuses; neither becomes zero |
| Lineage | Formula → named input → full fact ID → concept, dates and accession |
| Replay | Hash checks and full recomputation of CSV, JSON, decisions, lineage and HTML |

Nine outputs: net margin, operating margin, cash conversion, current ratio, liability ratio, free cash flow, FCF margin, accounting balance residual and reported annual revenue growth. Fractions preserve exact values; decimal display is rounded. Growth is **not week-normalized**. Its base must be the immediately preceding configured period with an adjacent calendar: the earlier end must be exactly one day before the current start. A skipped year or calendar gap keeps the current-period metrics and marks growth `missing_input` for `previous_period_revenue`.

## Demo evidence

- FY2024 is unavailable on `2024-10-31` and available on `2024-11-01`.
- FY2023 has 371 inclusive days; FY2024 has 364.
- FY2024 free cash flow is USD **108,807 million**, calculated from operating cash flow minus capex payments.
- At the later cutoff, FY2023 comparative records come from the 2024 filing with unchanged amounts. No actual restatement is claimed.

There are six cutoff/period panels and nine metrics per panel. Missing panels remain visibly missing. `verify` rejects output tampering even when the corresponding hash is updated; it does not authenticate source inputs or detect a coordinated rewrite of all inputs and outputs.

`verify` also rebuilds HTML byte for byte using the installed renderer. Verify
an older report with the source revision that generated it. After this HTML
update, rebuild a new report from the saved facts and request into a new
directory; do not replace evidence you need to retain. An HTML mismatch between
renderer revisions alone does not establish that the old report was tampered with.

## Saved-input analysis and validation

```bash
statementtrace run --facts companyfacts.json \
  --request src/statementtrace/data/demo_request.json --out output/custom
python -m pip install -e '.[dev]'
python -m unittest discover -s tests -v
ruff check src tests scripts
ruff format --check src tests scripts
statementtrace verify examples/demo
```

Supply the issuer's actual fiscal calendar. Eleven configured US-GAAP concepts and integral USD raw values are supported; this is not a universal XBRL parser. Save external data separately following the [SEC API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces). The demo and verifier need no network access or credentials.

Tests cover time cutoffs, comparative selection, 53-week periods, quarterly exclusions, ambiguity, exact arithmetic, malformed JSON and evidence tampering. An independent SQLite query checks every demo selection. Real Chrome checks both report selectors, shared-link round trips, history restoration, malformed links and exact special-character period identities at desktop and narrow widths, plus the no-JavaScript fallback. Both panel CSV downloads are compared with full-export slices, and two periods' files must coexist at one cutoff. CI runs tests, byte-for-byte committed report replay and installed-wheel smoke tests on Linux Python 3.11–3.13 and Windows Python 3.12. Text files keep LF endings even with Git's Windows `core.autocrlf=true` setting, so a fresh checkout preserves report hashes. The real symlink test requires Windows Developer Mode or elevated privileges; only that test skips if Windows denies link creation.

CSV review exports mark formula-shaped period names as text and quote embedded
carriage returns. Original labels remain in JSON; numeric financial evidence is
unchanged. See the [spreadsheet export contract](docs/METHODOLOGY.md#spreadsheet-exports).

## 中文说明

公开财报数据处理与财务指标追溯项目，适合金融数据、财报分析与风控实习展示。重点可以讲 **申报截止日、53 周财年、比较期数据、SQL 对照、缺失值契约和指标血缘**。

- [方法与边界](docs/METHODOLOGY.md)
- [公开数据来源](docs/SOURCES.md)
- [可复算演示](examples/demo)

Code: MIT. Financial facts retain filing attribution; the license does not relicense third-party filings. No production-service, investment-return or credit-rating claim is made.

# Public source ledger

| Source | Filing date | Extracted tables |
|---|---|---|
| [Apple FY2023 Form 10-K](https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/aapl-20230930.htm), [filing index](https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/0000320193-23-000106-index.htm) | 2023-11-03 | Operations p.28, balance sheet p.30, cash flows p.32 |
| [Apple FY2024 Form 10-K](https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm), [filing index](https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/0000320193-24-000123-index.htm) | 2024-11-01 | Operations p.29, balance sheet p.31, cash flows p.33 |
| [SEC XBRL APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) | Input format reference | CompanyFacts concept/unit arrays |

Eleven concepts comprise five duration and six instant facts. Each has FY2023 values from both filings plus FY2024 values: **33 records**. USD-million table values are scaled by 1,000,000. Capex is a positive outflow magnitude. Cash comes from the balance sheet, avoiding confusion with the cash-flow statement's broader restricted-cash amount.

FY2023 spans 2022-09-25 to 2023-09-30 (53 weeks); FY2024 spans 2023-10-01 to 2024-09-28 (52 weeks). Constructed metadata includes concept mapping, `fy`, `fp` and `source_section`. Comparative values are unchanged; synthetic amendments appear only in tests. This is a manually curated excerpt, not an unmodified API response or complete issuer dataset. Reviewed 2026-10-08.

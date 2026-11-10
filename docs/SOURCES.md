# Public source ledger

| Source | Filing date | Extracted tables |
|---|---|---|
| [Apple FY2023 Form 10-K](https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/aapl-20230930.htm), [filing index](https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/0000320193-23-000106-index.htm) | 2023-11-03 | Operations p.28, balance sheet p.30, cash flows p.32 |
| [Apple FY2024 Form 10-K](https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm), [filing index](https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/0000320193-24-000123-index.htm) | 2024-11-01 | Operations p.29, balance sheet p.31, cash flows p.33 |
| [SEC XBRL APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) | Input format reference | CompanyFacts concept/unit arrays |

Eleven concepts comprise five duration and six instant facts. Each has FY2023 values from both filings plus FY2024 values: **33 records**. USD-million table values are scaled by 1,000,000. Capex is a positive outflow magnitude. Cash comes from the balance sheet, avoiding confusion with the cash-flow statement's broader restricted-cash amount.

FY2023 spans 2022-09-25 to 2023-09-30 (53 weeks); FY2024 spans 2023-10-01 to 2024-09-28 (52 weeks). Constructed metadata includes concept mapping, `fy`, `fp` and `source_section`. Comparative values are unchanged; synthetic amendments appear only in tests. This is a manually curated excerpt, not an unmodified API response or complete issuer dataset. Reviewed 2026-10-08.

## Cross-issuer cash-flow case — reviewed 2026-11-10

The separate [cash-flow source packet](../src/statementtrace/data/cashflow_case.json)
uses four duration concepts for two years per issuer: revenue, net income,
operating cash flow and cash purchases of property, plant and equipment.
All 24 records are manually curated from the comparative columns of the
following FY2024 filings, then scaled from USD millions to integral USD.
Cash capex is stored as a positive outflow magnitude. This does not add to or
rewrite the original 33-record Apple cutoff demo.

| Issuer | Filing and filed date | Exact fiscal windows |
| --- | --- | --- |
| Apple | [FY2024 10-K](https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm), 2024-11-01; statements of operations and cash flows | FY2023: 2022-09-25–2023-09-30; FY2024: 2023-10-01–2024-09-28 |
| Microsoft | [FY2024 10-K](https://www.sec.gov/Archives/edgar/data/789019/000095017024087843/msft-20240630.htm), [index](https://www.sec.gov/Archives/edgar/data/789019/000095017024087843/0000950170-24-087843-index.htm), 2024-07-30; income and cash flows statements | FY2023: 2022-07-01–2023-06-30; FY2024: 2023-07-01–2024-06-30 |
| Alphabet | [FY2024 10-K](https://www.sec.gov/Archives/edgar/data/1652044/000165204425000014/goog-20241231.htm), [index](https://www.sec.gov/Archives/edgar/data/1652044/000165204425000014/0001652044-25-000014-index.htm), 2025-02-05; consolidated statements of income and cash flows | FY2023: 2023-01-01–2023-12-31; FY2024: 2024-01-01–2024-12-31 |

All are visible at the historical case cutoff of 2025-02-05. The Alphabet index
shows acceptance on February 4 at 20:41:40 and a filed date of February 5;
selection consistently uses the filed date, not an inferred intraday rule.
Earlier-cutoff missing values describe this packet's coverage, not the absence
of prior public filings. No calendar alignment or week normalization is implied.

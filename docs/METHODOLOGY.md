# Selection and metric contracts

The input uses `cik`, `entityName`, `facts.us-gaap.<concept>.units.<unit>[]`. Demo records are transcribed, CompanyFacts-shaped objects; `_statementtrace` records their provenance and USD-million conversion. They are not a raw API extraction.

Selection matches the configured fiscal start/end for duration facts, or only the end for instant facts. It accepts USD annual forms and keeps records with `filed <= as_of`. The latest filed date wins. Conflicting values on that date fail; identical values tie by explicit alias order, accession and content ID. Identical duplicates are collapsed. Row order never determines results.

`fy` is retained as filing metadata, not used as a period selector. A later filing may repeat older-period facts. Cutoffs use the SEC **filed date**, not acceptance timestamps: the 2023 filing was accepted November 2 but has a November 3 filed date. No intraday trading availability is claimed.

Configured period labels are unique identifiers, not inferred year numbers. Report selector values preserve the full label, including whitespace, quotes and escaped markup, so each selected cutoff/period pair resolves to its corresponding panel. Explicit values avoid the [HTML option text fallback](https://html.spec.whatwg.org/multipage/form-elements.html#the-option-element), which strips and collapses ASCII whitespace and can make distinct labels collide.

Monetary inputs are integer USD; booleans, floats and numeric strings fail. Negative income/equity is supported. Derived values use exact fractions, with isolated half-even decimal display.

| Output | Formula |
|---|---|
| Net / operating margin | Income / revenue |
| Cash conversion | Operating cash flow / net income |
| Current ratio | Current assets / current liabilities |
| Liability ratio | Total liabilities / total assets |
| Free cash flow | Operating cash flow − capex payments |
| FCF margin | Free cash flow / revenue |
| Balance residual | Assets − liabilities − equity |
| Revenue growth | Revenue / immediately preceding, calendar-adjacent configured period revenue − 1 |

FCF is a defined analytic convention. Growth compares reported periods without week normalization. The caller supplies the issuer's annual fiscal calendar; the engine requires the previous configured period to end exactly one day before the current one starts. It does not infer adjacency from labels or divide a multi-year change into an annual rate. A skipped year or even a one-day gap leaves current-period facts and other metrics available but marks growth `missing_input` for `previous_period_revenue`, without linking the non-adjacent period as an input. A 53-week year followed by a 52-week year remains valid when the dates are adjacent. Missing input and zero denominator have distinct statuses. A nonzero balance residual is evidence, not an automatic repair.

The verifier enforces the fixed member set, rejects symlinks, checks hashes and regenerates all files, including HTML and source links. It catches output-only corruption with rewritten hashes; it cannot authenticate source data or detect a complete coordinated rewrite. The independent SQL test oracle checks selection on the demo, not arbitrary issuers' accounting policies.

## Spreadsheet exports

Period labels are untrusted text. Formula-shaped labels (including full-width
variants and prefixes behind ASCII whitespace) and leading control/BOM prefixes
receive a visible `text: ` marker in all four CSV exports. Labels already starting
with that marker receive one more marker, keeping distinct labels distinct.
Original identities remain unchanged in `request.json`, `analysis.json` and HTML.
USD amounts, negative ratios, exact fractions and decimal displays are unchanged.

CSV records retain LF endings, while embedded CR, LF and CRLF are quoted as cell
content. This prevents a carriage return in a label from creating a new record.
The visible marker avoids relying on apostrophes that some spreadsheet editors
remove on save/reopen; see [OWASP's CSV injection guidance](https://owasp.org/www-community/attacks/CSV_Injection).
CSV is a review representation; use the JSON for original labels and replay.
The committed numerical tables and source data are unchanged. Regenerate earlier reports from their saved JSON inputs before verification
with the updated exporter and selector renderer.

Unsupported: custom issuer taxonomies, segmented facts, IFRS models, currency conversion, fractional raw monetary facts, intraday availability and automated restatement reconciliation.

HTML selectors use explicit ASCII JSON identity keys shared with their result
rows/panels. This preserves distinct repeated-whitespace, CR/LF, NUL and Unicode
identities through browser preprocessing; visible labels and source JSON retain
the original text. Saved report HTML and its manifest hash were refreshed without
changing financial values or source data.

The `Chrome report selectors` CI job selects these identities in actual Chrome,
checking that each choice shows the intended result. It uses the Ubuntu runner's
Chrome/chromedriver and no extra Python package. Run
`python scripts/check_browser.py` with matching Chrome and chromedriver installed
(or set `CHROMEWEBDRIVER` to the driver's directory) to reproduce it.

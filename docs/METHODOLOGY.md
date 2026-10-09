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
| Revenue growth | Revenue / immediately preceding configured period revenue − 1 |

FCF is a defined analytic convention. Growth compares reported periods without week normalization; the caller is responsible for specifying appropriate consecutive annual periods. Missing input and zero denominator have distinct statuses. A nonzero balance residual is evidence, not an automatic repair.

The verifier enforces the fixed member set, rejects symlinks, checks hashes and regenerates all files, including HTML and source links. It catches output-only corruption with rewritten hashes; it cannot authenticate source data or detect a complete coordinated rewrite. The independent SQL test oracle checks selection on the demo, not arbitrary issuers' accounting policies.

Unsupported: custom issuer taxonomies, segmented facts, IFRS models, currency conversion, fractional raw monetary facts, intraday availability and automated restatement reconciliation.

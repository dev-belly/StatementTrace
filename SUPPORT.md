# Support for StatementTrace

Start with [the quick start](README.md), [methodology](docs/METHODOLOGY.md) and [source notes](docs/SOURCES.md). To check the committed evidence after installation:

```bash
statementtrace verify examples/demo
python scripts/check_demo.py
```

For a selection or ratio problem, open a [bug report](https://github.com/dev-belly/StatementTrace/issues/new/choose) with the command, package revision, OS/Python, cutoff, exact fiscal period, concept/unit and expected versus selected fact. A few synthetic CompanyFacts-shaped records are more useful than an entire issuer download. Include missing-input or zero-denominator status when relevant.

Amounts in the example come from manually curated filing records; the verifier checks replay consistency, not the authenticity of a supplied filing. Consult [the contribution guide](CONTRIBUTING.md) before changing contracts or saved evidence. For a suspected vulnerability, follow [SECURITY.md](SECURITY.md); do not attach private financial documents.

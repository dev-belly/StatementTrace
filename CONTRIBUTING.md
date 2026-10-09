# Contributing

Use Python 3.11 or newer. Install `python -m pip install -e '.[dev]'`, then run:

```bash
python -m unittest discover -s tests -v
ruff check src tests scripts
ruff format --check src tests scripts
python scripts/check_demo.py
python scripts/generate_preview.py --check
```

Keep amount and availability contracts explicit. Regression coverage must justify
changes in SQL, exact dates, aliases and ratio lineage. If a change intentionally modifies output, regenerate
`examples/demo` in a separate empty directory, compare the diff, replace the
tracked evidence, regenerate the preview, and explain the changed result.
Never update expected evidence automatically inside CI. Preserve source attribution
and identify synthetic fixtures as synthetic.

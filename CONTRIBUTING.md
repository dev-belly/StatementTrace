# Contributing

Use Python 3.11 or newer. Install `python -m pip install -e '.[dev]'`, then run:

```bash
python -m unittest discover -s tests -v
ruff check src tests scripts
ruff format --check src tests scripts
python scripts/check_demo.py
python scripts/check_cashflow.py
python scripts/generate_preview.py --check
```

On Windows PowerShell, install with `.\.venv\Scripts\python.exe -m pip install -e '.[dev]'`
and use `.\.venv\Scripts\python.exe` / `.\.venv\Scripts\ruff.exe` for the commands above.
Running those executables directly avoids activation scripts and changes to PowerShell's execution policy.
Committed reports and previews use LF endings through `.gitattributes`; keep their exact bytes
instead of rewriting the hash manifest after a line-ending conversion. CI also tests a Windows
checkout with `core.autocrlf=true`, replay, and an installed wheel outside the source directory.
On Windows without symlink privileges, only the real symlink test skips; the Linux jobs always
exercise it. Other I/O errors remain test failures.

Keep amount and availability contracts explicit. Regression coverage must justify
changes in SQL, exact dates, aliases and ratio lineage. If a change intentionally modifies output, regenerate
`examples/demo` in a separate empty directory, compare the diff, replace the
tracked evidence, regenerate the preview, and explain the changed result.
Never update expected evidence automatically inside CI. Preserve source attribution
and identify synthetic fixtures as synthetic.

For the optional financial warehouse, install the checked lock and run the real engines:

```bash
uv sync --locked --extra warehouse --extra dbt --extra dev
uv run --locked python -m unittest discover -s tests -v
uv run --locked statementtrace warehouse --out output/warehouse
uv run --locked statementtrace verify-warehouse output/warehouse
uv run --locked python scripts/check_warehouse_dbt.py output/warehouse
uv run --locked statementtrace warehouse --as-of 2025-02-04 --out output/early
uv run --locked python scripts/check_warehouse_dbt.py output/early
```

The base test job intentionally skips the columnar tests when their extra is absent;
the separate warehouse matrix installs the locked engines and runs every test.
The dbt script builds models and tests, checks exact mart parity and requires a
one-row future-filing mutation to fail the named cutoff test. Keep dbt SQL changes
consistent with Python expectations and the packaged direct DuckDB query.

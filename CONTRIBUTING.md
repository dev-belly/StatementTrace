# Contributing

Use Python 3.11 or newer. Install `python -m pip install -e '.[dev]'`, then run:

```bash
python -m unittest discover -s tests -v
ruff check src tests scripts
ruff format --check src tests scripts
python scripts/check_demo.py
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

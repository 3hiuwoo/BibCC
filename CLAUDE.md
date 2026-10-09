# CLAUDE.md - BibCC

See **README.md** for commands, options, architecture, template workflow, and output files.

## Environment

```bash
uv sync                # create/refresh .venv
uv run bibcc --help    # run the CLI
uv run pytest          # run the tests
```

## Code Conventions

- **Package layout**: all code lives in `src/bibcc/`; import with absolute `bibcc.` paths (no `sys.path` hacks).
- **No raw `print()`** — always accept and use a `log: Callable[[str], None]` callback.
- **Output format constants** live in `bibcc/logging_utils.py` — use `SEPARATOR_WIDTH`, `SEPARATOR_HEAVY`, `SEPARATOR_LIGHT`, `SEPARATOR_THIN`, `Logger`, `write_report`. Never hard-code widths or separator characters.
- **CLI pattern**: main tools expose `build_parser()` → `run(args)`; utils tools use `build_parser()` + `main()` with subparsers. Register new tools in `bibcc/cli.py`.
- **Help pages**: build parsers with `bibcc.helptext.HelpFormatter` and an `epilog(...)` (examples, output files, exit status, environment). `tests/test_cli.py` requires a description, examples, and help text on every option.
- **Version and changelog**: the version lives only in `src/bibcc/__init__.py` (`pyproject.toml` reads it). Record user-visible changes in `CHANGELOG.md` under the top, unreleased version.
- **Venue library**: lives in `bibcc/data/venues.yaml`; load and save it through `bibcc.venues.VenueLibrary`. When hand-writing YAML strings (e.g. the missing-venues file), quote them with `json.dumps` so backslashes and quotes are escaped.
- **Network access**: go through `bibcc.sources.fetch_url` / `fetch_json`, so tests can monkeypatch one function. Tests never hit the network; canned API responses live in `tests/fixtures/sources/`.
- **Tests**: add tests under `tests/` for new behaviour; never touch the real survey bibliography in tests.

## Git

- **No Co-Authored-By signature** in commit messages.
- **Commit message style**: lowercase `verb: short description` (e.g. `add: feature`, `fix: bug`).

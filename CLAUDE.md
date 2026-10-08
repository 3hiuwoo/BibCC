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
- **YAML venue names**: escape backslashes — `venue.replace("\\", "\\\\")`.
- **Tests**: add tests under `tests/` for new behaviour; never touch the real survey bibliography in tests.

## Git

- **No Co-Authored-By signature** in commit messages.
- **Commit message style**: lowercase `verb: short description` (e.g. `add: feature`, `fix: bug`).

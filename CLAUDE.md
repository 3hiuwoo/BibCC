# CLAUDE.md - BibCC

See **README.md** for commands, options, architecture, template workflow, and output files.

## Environment

```bash
mamba activate pmq
```

## Code Conventions

- **No raw `print()`** — always accept and use a `log: Callable[[str], None]` callback.
- **Output format constants** live in `logging_utils.py` — use `SEPARATOR_WIDTH`, `SEPARATOR_HEAVY`, `SEPARATOR_LIGHT`, `SEPARATOR_THIN`, `Logger`, `write_report`, `get_repo_dir`. Never hard-code widths or separator characters.
- **CLI pattern**: main tools expose `build_parser()` → `run(args)`; utils tools use `build_parser()` + `main()` with subparsers.
- **YAML venue names**: escape backslashes — `venue.replace("\\", "\\\\")`.

## Git

- **No Co-Authored-By signature** in commit messages.
- **Commit message style**: lowercase `verb: short description` (e.g. `add: feature`, `fix: bug`).

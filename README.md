# BibCompletion (Under Development)

## File Explain

- **`main.py` / `completer.py`**: Core completion tool. Reads a source `.bib`, matches entries against `templates.py`, and fills missing fields. Supports dry-run and logs for conflicts & missing (venue, year).
  - Dry-run (default if no `--output`): `python completer.py input.bib`
  - Write output: `python completer.py input.bib --output output.bib`
  - Logs: `--conflict-log path.txt` and `--missing-log path.txt` (defaults: `input.bib.conflicts.txt`, `input.bib.missing_templates.txt`)

- **`checker.py`**: Unified validation tool. Checks missing fields, Title Case, and smart protection for technical terms.
  - Missing fields: `python checker.py input.bib --fields month,publisher --entry-types inproceedings,article`
  - Title Case (APA default): `python checker.py input.bib --title-case --title-style apa`
  - Smart protection (quoting): `python checker.py input.bib --quote --quote-terms Gaussian,Kalman --quote-vocab-file my_terms.txt`

- **`titlecase_checker.py`**: Standalone Title Case checker (shares logic with checker). Default style: **APA** (first word, words ≥4 letters, major words, and all parts of hyphenated major words like `Class-Incremental`). Usage: `python titlecase_checker.py input.bib --style apa`

- **`quoter.py`**: Thin wrapper to run only the smart-protection scan (uses the unified checker logic).
  - Usage: `python quoter.py input.bib --terms Gaussian,Kalman` or `--vocab-file my_terms.txt`

- **`bib2py.py`**: Convert BibTeX entries to `templates.py` format and (optionally) append new templates automatically.
  - Print snippets only: `python bib2py.py new_confs.bib`
  - Auto-append missing keys to templates (backup created): `python bib2py.py new_confs.bib --update --templates-path templates.py`

## TODO

1. Complete Readme
2. Refine Project Structure
3. Add more annotations
4. Support commandline arg. parsing
5. Support more general functionality
6. Refine the code including unifying variable names, unifying string formatting, etc.
7. Pack all things up
8. Support web claw or LLM assisting template completion

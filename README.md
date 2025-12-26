# 📚 BibTex Check & Complete (BibCC)

Small BibTeX utility toolkit to auto-complete missing fields, check formatting quality, and maintain reusable templates.

## 🚀 Quick start

```bash
pip install bibtexparser
```

### 🧩 Complete missing fields — `completer.py`

- Preview only (no write-back, logs generated):

  ```bash
  python completer.py input.bib
  ```

- Choose a log directory: `--log-dir logs/` (default current directory, outputs `*.conflicts.txt` and `*.missing_templates.txt`).

- Write completed output (overwrites the given output path):

  ```bash
  python completer.py input.bib --output output.bib
  ```

### ✅ Quality checks — `checker.py`

- Missing-field check (default entry types: inproceedings, article, proceedings, conference):

  ```bash
  python checker.py input.bib --fields month,publisher
  ```

- Title Case suggestions (APA style by default, change with `--title-style apa`):

  ```bash
  python checker.py input.bib --title-case --title-style apa
  ```

- Smart protection for technical terms (suggest braces), with optional custom vocab:

  ```bash
  python checker.py input.bib --quote --quote-terms Gaussian,Kalman --quote-vocab-file my_terms.txt
  # To skip built-in vocab, add --quote-no-default
  ```

### 🗂️ Maintain the template library — `bib2py.py`

- Generate template snippets from a `.bib` file (print only, do not write):

  ```bash
  python bib2py.py new_confs.bib
  ```

- Merge into `templates.py` directly (sorted by year descending, auto-creates a `.bak` backup):

  ```bash
  python bib2py.py new_confs.bib --update --templates-path templates.py
  ```

## 🧭 Suggested workflow

### 🛠️ Completion

1. Run `completer.py input.bib` without output to check missing fields, conflict fields and missing-template.

2. Resolve conflict fields by updating templates or entry.

3. Gather new venue/year combos into a separate `.bib` (under `templates/`) and run `bib2py.py --update` to refresh `templates.py` for future reuse.

4. Run `completer.py input.bib --output output.bib` to complete the file. (See Additional resources for additional formatting)

### 🔍 Validation

Run `checker.py` to:

- `--fields` find required-field gaps;
- `--title-case` get Title Case suggestions;
- `--quote` spot technical terms needing braces.

## 🧾 Templates

- Main templates live in `templates.py`, keyed by `(venue, year)` with a dict of fields to fill.
- The `templates/` folder holds historical/backup `.bib` files for reference.

## 🔗 Additional resources

The modified `.bib` file is not guaranteed to be well formatted, thanks to [**BibTex Tidy**](https://flamingtempura.github.io/bibtex-tidy/) and VS Code's LaTex Workshop extension for final formatting.

Feel free to extend templates and vocab to match your bibliography!

# BibCompletion (Under Development)

## File Explain

- **`main.py`**: The core tool. It reads a source `.bib` file, matches entries against predefined templates in `templates.py`, and fills in missing fields (e.g., address, month, publisher) into a new output file.
  - Usage: `python main.py input.bib output.bib`

- **`checker.py`**: A validation tool that scans a `.bib` file to identify entries (like conference papers or articles) that are missing the `month` field.
  - Usage: `python checker.py input.bib`

- **`quoter.py`**: A "smart protection" scanner. It checks titles in a `.bib` file for terms that likely need curly brace protection (e.g., acronyms like "BERT", mixed-case terms like "ResNet", or hyphenated proper nouns).
  - Usage: `python quoter.py input.bib`

- **`calculator.py`**: A helper tool to analyze a `.bib` file and list all unique (Venue, Year) combinations. It helps identify which venues are missing from your `templates.py`.
  - Usage: `python calculator.py input.bib`

- **`bib2py.py`**: A utility script to convert raw BibTeX entries into the Python dictionary format required for `templates.py`. Useful for bulk-adding new templates.
  - Usage: `python bib2py.py input.bib`

## TODO

1. Complete Readme
2. Refine Project Structure
3. Add more annotations
4. Support commandline arg. parsing
5. Support more general functionality
6. Refine the code including unifying variable names, unifying string formatting, etc.
7. Pack all things up
8. Support web claw or LLM assisting template completion

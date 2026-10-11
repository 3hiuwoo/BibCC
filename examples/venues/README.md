# Example Venue Libraries

BibCC ships no venue library. Every user builds their own: a **user library** (`~/.config/bibcc/venues.yaml`, or `$BIBCC_VENUES`) for all their projects, and optionally a **project library** (`.bibcc-venues.yaml`, committed with the bibliography) for one project. See [Venue Library](../../README.md#venue-library) in the README.

The libraries in this folder are a head start. Each one was built by a lab or a person for their own field, so check it fits your needs rather than taking it as a standard.

| Library | Maintained by | Covers |
| --- | --- | --- |
| [`miaa`](miaa.yaml) | MIAA lab ([@3hiuwoo](https://github.com/3hiuwoo)) | Machine learning, computer vision, and multimedia: 30 journals (IEEE TPAMI, TIP, TNNLS, TCSVT, IJCV, Pattern Recognition, Neurocomputing, TMLR, ...) and 75 proceedings from 2016 to 2026 (CVPR, ICCV, ECCV, WACV and their workshops, NeurIPS, ICML, ICLR, AAAI, IJCAI, ACM MM, ACL, NAACL, KDD, WSDM, MICCAI, BMVC, ...), with the CVF and OpenReview interim booktitles linked |

## Using One

```bash
bibcc venues examples                        # list the libraries in this folder
bibcc venues import miaa --dry-run           # preview what it would add to your user library
bibcc venues import miaa                     # merge it into your user library
bibcc venues import miaa --scope project     # or into the project's .bibcc-venues.yaml
```

`import` reads the library from your checkout when BibCC runs from one, and from GitHub otherwise. It only adds: records you don't have yet are added, and records you already have gain the fields, aliases, and interim booktitles they lack. Where a field differs, your value is kept and the difference is listed, unless you pass `--overwrite`. You can import a library file or a URL the same way (`bibcc venues import ~/lab.yaml`, `bibcc venues import https://...`).

## Contributing a Library

Share your library so others in your field can start from it:

1. Name it after the lab, group, or field, in lowercase letters, digits, and hyphens (`examples/venues/<name>.yaml`).
2. Write it with BibCC, so it is in the canonical, sorted form that keeps diffs small:

   ```bash
   bibcc venues import ~/.config/bibcc/venues.yaml --venues examples/venues/<name>.yaml
   ```

3. Check it for records missing fields, and fill in what you can:

   ```bash
   bibcc check --check-venues --venues examples/venues/<name>.yaml
   ```

4. Add a row to the table above (name, who maintains it, what it covers).
5. Open a pull request. CI checks that every library here loads and is in canonical form (`tests/test_scopes.py`).

Take values from official sources, such as the publisher's or the proceedings' own pages, not from other bibliographies. To improve someone else's library, open a pull request that edits it, and the library's maintainer reviews it.

### Keeping a Library Up to Date

As a maintainer, you keep adding venues to your own user or project library as you work. To refresh the shared copy from your library:

```bash
bibcc venues import ~/.config/bibcc/venues.yaml --venues examples/venues/<name>.yaml --overwrite
```

`--overwrite` makes your library's values replace older ones in the shared copy. Records are never removed by `import`; delete those by hand.

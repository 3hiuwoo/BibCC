# Example venue libraries

BibCC doesn't ship a venue library. Every user builds their own: a user library (`~/.config/bibcc/venues.yaml`, or `$BIBCC_VENUES`) for all their projects, and optionally a project library (`.bibcc-venues.yaml`, committed with the bibliography) for one project. For details, see [Venue library](../../README.md#venue-library) in the BibCC README.

The libraries in this directory give you a head start. A lab or a person built each one for their own field, so check that it fits your needs rather than taking it as a standard.

The following table lists the libraries in this directory:

| Library | Maintained by | Covers |
| --- | --- | --- |
| [`miaa`](miaa.yaml) | MIAA lab ([@3hiuwoo](https://github.com/3hiuwoo)) | Machine learning, computer vision, and multimedia: 30 journals (including IEEE TPAMI, TIP, TNNLS, TCSVT, IJCV, Pattern Recognition, Neurocomputing, and TMLR) and 75 proceedings from 2016 to 2026 (including CVPR, ICCV, ECCV, WACV and their workshops, NeurIPS, ICML, ICLR, AAAI, IJCAI, ACM MM, ACL, NAACL, KDD, WSDM, MICCAI, and BMVC), with the CVF and OpenReview interim booktitles linked |

## Using a library

To use a library from this directory, import it into your user library or project library:

```bash
bibcc venues examples                        # list the libraries in this directory
bibcc venues import miaa --dry-run           # preview what it would add to your user library
bibcc venues import miaa                     # merge it into your user library
bibcc venues import miaa --scope project     # or into the project's .bibcc-venues.yaml
```

When BibCC runs from a checkout, `import` reads the library from the checkout. Otherwise, it reads the library from GitHub.

`import` only adds. It adds the records you don't have yet, and it adds the fields, aliases, and interim booktitles that your existing records lack. Where a field differs, `import` keeps your value and lists the difference, unless you pass `--overwrite`. You can import a library file or a URL the same way, for example `bibcc venues import ~/lab.yaml` or `bibcc venues import URL`.

## Contributing a library

To share your library so that others in your field can start from it, follow these steps:

1. Name it after the lab, group, or field, in lowercase letters, digits, and hyphens (`examples/venues/NAME.yaml`).
2. To put it in the canonical, sorted form that keeps diffs small, write it with BibCC:

   ```bash
   bibcc venues import ~/.config/bibcc/venues.yaml --venues examples/venues/NAME.yaml
   ```

3. Check it for records with missing fields, and fill in what you can:

   ```bash
   bibcc check --check-venues --venues examples/venues/NAME.yaml
   ```

4. Add a row for it to the [table of libraries](#example-venue-libraries): its name, who maintains it, and what it covers.
5. Open a pull request. CI checks that every library in this directory loads and is in canonical form (`tests/test_scopes.py`).

Take values from official sources, such as the publisher's or the proceedings' own pages, not from other bibliographies. To improve someone else's library, open a pull request that edits it. The library's maintainer reviews it.

### Keeping a library up to date

As a maintainer, you keep adding venues to your own user library or project library as you work. To refresh the shared copy from your library, run the following command:

```bash
bibcc venues import ~/.config/bibcc/venues.yaml --venues examples/venues/NAME.yaml --overwrite
```

With `--overwrite`, your library's values replace older values in the shared copy. `import` never removes records; to remove a record, delete it by hand.

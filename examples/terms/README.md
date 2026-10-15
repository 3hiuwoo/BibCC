# Example terms files

BibCC's `check quote` keeps your protected terms in {braces}: acronyms such as `CLIP`, mixed-case names such as `LoRA`, and method names such as `CIP-Net`. Like the venue library, terms live in two scopes: a user terms file (`~/.config/bibcc/terms.txt`, or `$BIBCC_TERMS`) for all your projects, and optionally a project terms file (`.bibcc-terms.txt`, committed with the bibliography) for one project. For details, see [Protected terms](../../README.md#protected-terms) in the BibCC README.

The files in this directory give you a head start. A lab or a person built each one for their own field, so check that it fits your needs rather than taking it as a standard.

The following table lists the files in this directory:

| File | Maintained by | Covers |
| --- | --- | --- |
| [`miaa`](miaa.txt) | MIAA lab ([@3hiuwoo](https://github.com/3hiuwoo)) | Machine learning and computer vision: model and dataset names (CLIP, ViT, ImageNet, and LoRA) and the venue acronyms of booktitles (CVPR, NeurIPS, and ICLR) |

## Using a terms file

To use a file from this directory, import it into your user terms file or project terms file:

```bash
bibcc terms examples                        # list the files in this directory
bibcc terms import miaa --dry-run           # preview what it would add to your user terms
bibcc terms import miaa                     # add its terms to your user terms
bibcc terms import miaa --scope project     # or to the project's .bibcc-terms.txt
```

`import` only adds the terms that your file lacks, ignoring case. When BibCC runs from a checkout, `import` reads the file from the checkout. Otherwise, it reads the file from GitHub.

## Contributing a terms file

To share your terms, add `examples/terms/NAME.txt`, named after the lab, group, or field in lowercase letters, digits, and hyphens. Start it with a comment that says who it's for, add a row for it to the [table of files](#example-terms-files), and open a pull request.

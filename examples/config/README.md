# Example configs

A config file holds your settings for BibCC commands: a user config (`~/.config/bibcc/config.yaml`, or `$BIBCC_CONFIG`) for all your projects, and optionally a project config (`.bibcc.yaml`, committed with the bibliography) for one project. For details, see [Config files](../../README.md#config) in the BibCC README.

The configs in this directory give you a head start. A lab or a person wrote each one for their own bibliography, so check that it fits your needs rather than taking it as a standard.

The following table lists the configs in this directory:

| Config | Maintained by | Sets |
| --- | --- | --- |
| [`miaa`](miaa.yaml) | MIAA lab ([@3hiuwoo](https://github.com/3hiuwoo)) | The `format` layout of the lab's surveys: the title-first field order with `citation` last, and every other style setting written out |

## Using a config

To use a config from this directory, import it into your user config or project config:

```bash
bibcc config examples                        # list the configs in this directory
bibcc config import miaa --dry-run           # preview what it would change in your user config
bibcc config import miaa --scope project     # merge it into the project's .bibcc.yaml
bibcc config where bib/                      # check the settings that apply
```

When BibCC runs from a checkout, `import` reads the config from the checkout. Otherwise, it reads the config from GitHub.

`import` adds the settings that your file lacks. Where a setting differs, `import` keeps your value and lists the difference, unless you pass `--overwrite`. You can import a config file or a URL the same way, for example `bibcc config import ~/lab-config.yaml`.

## Contributing a config

To share your config, follow these steps:

1. Name it after the lab, group, or style, in lowercase letters, digits, and hyphens (`examples/config/NAME.yaml`).
2. Check that BibCC reads it without warnings:

   ```bash
   bibcc config import examples/config/NAME.yaml --config /tmp/check.yaml --dry-run
   ```

3. Add a row to the preceding table, and open a pull request to `dev`.

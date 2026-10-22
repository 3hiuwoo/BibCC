// The bibcc commands the workbench exposes, with the options each one accepts.
// Derived from `bibcc surface`; only the commands that work offline are included,
// because the browser cannot reach CrossRef, arXiv, or publisher sites.
//
// Option kinds: bool (a flag), text/number (a flag with a value), select (a flag
// with one of several values), tri (a paired --flag/--no-flag left at its default).

const CHECKS = "Rewrite or report on the file";

export const COMMANDS = [
  {
    id: "format",
    group: CHECKS,
    label: "format",
    summary: "Reformat consistently: aligned fields, braced values, month macros, and -- page ranges.",
    argv: ["format", "input.bib"],
    options: [
      { flag: "--in-place", kind: "bool", label: "Write the result into the file", hint: "Without it, format is a dry run that only writes a diff report.", primary: true, defaultOn: true },
      { flag: "--check", kind: "bool", label: "Only report whether the file is already formatted" },
    ],
    advanced: [
      { flag: "--sort-fields", neg: "--no-sort-fields", kind: "tri", label: "Sort fields" },
      { flag: "--field-order", kind: "text", label: "Field order", placeholder: "title,author,year,*" },
      { flag: "--sort-entries", neg: "--no-sort-entries", kind: "tri", label: "Sort entries" },
      { flag: "--keep-quotes", neg: "--no-keep-quotes", kind: "tri", label: "Keep quoted values" },
      { flag: "--keep-outer-braces", neg: "--no-keep-outer-braces", kind: "tri", label: "Keep outer braces" },
      { flag: "--keep-months", neg: "--no-keep-months", kind: "tri", label: "Keep months as written" },
      { flag: "--keep-pages", neg: "--no-keep-pages", kind: "tri", label: "Keep page ranges as written" },
      { flag: "--align", neg: "--no-align", kind: "tri", label: "Align the = signs" },
      { flag: "--indent", kind: "number", label: "Indent width", placeholder: "2" },
      { flag: "--blank-lines", kind: "number", label: "Blank lines between entries", placeholder: "1" },
      { flag: "--trailing-comma", neg: "--no-trailing-comma", kind: "tri", label: "Trailing comma" },
      { flag: "--drop-empty", neg: "--no-drop-empty", kind: "tri", label: "Drop empty fields" },
      { flag: "--no-config", kind: "bool", label: "Ignore the config file" },
    ],
  },
  {
    id: "complete",
    group: CHECKS,
    label: "complete",
    summary: "Fill in missing venue fields from the venue library, and report conflicts.",
    argv: ["complete", "input.bib"],
    needs: ["venues"],
    options: [
      { flag: "--in-place", kind: "bool", label: "Write the result into the file", hint: "Without it, complete is a dry run that only reports what it would add.", primary: true, defaultOn: true },
      { flag: "--update-venues", kind: "bool", label: "Add the venues it filled in to the library" },
      { flag: "--resolve", kind: "select", label: "On conflict", choices: ["keep", "library"], hint: "keep your value, or take the library's" },
      { flag: "--fields", kind: "text", label: "Only these fields", placeholder: "publisher,month" },
      { flag: "--ids", kind: "text", label: "Only these citation keys", placeholder: "He_ResNet_CVPR2016" },
    ],
  },
  {
    id: "check-title",
    group: "Quality checks",
    label: "check title",
    summary: "Suggest APA-style Title Case for the titles, and optionally apply it.",
    argv: ["check", "title", "input.bib"],
    options: [
      { flag: "--apply", kind: "bool", label: "Rewrite the titles", primary: true, mutating: true },
      { flag: "--strict", kind: "bool", label: "Exit non-zero if anything is found" },
      { flag: "--extra-stopwords", kind: "text", label: "Extra stopwords", placeholder: "via,versus" },
    ],
  },
  {
    id: "check-quote",
    group: "Quality checks",
    label: "check quote",
    summary: "Report words that need {braces}, and compounds braced as a whole.",
    argv: ["check", "quote", "input.bib"],
    options: [
      { flag: "--apply", kind: "bool", label: "Brace your terms and split over-braced compounds", primary: true, mutating: true },
      { flag: "--terms", kind: "text", label: "Extra terms", placeholder: "LoRA,CLIP" },
      { flag: "--min-length", kind: "number", label: "Minimum word length", placeholder: "2" },
      { flag: "--no-default", kind: "bool", label: "Ignore the built-in vocabulary" },
      { flag: "--strict", kind: "bool", label: "Exit non-zero if anything is found" },
    ],
  },
  {
    id: "check-keys",
    group: "Quality checks",
    label: "check keys",
    summary: "Check that citation keys follow METHOD_AUTHOR_VENUEYEAR and match the entry.",
    argv: ["check", "keys", "input.bib"],
    options: [{ flag: "--strict", kind: "bool", label: "Exit non-zero if anything is found" }],
  },
  {
    id: "check-fields",
    group: "Quality checks",
    label: "check fields",
    summary: "Report unknown field names, malformed values, and duplicate papers.",
    argv: ["check", "fields", "input.bib"],
    options: [
      { flag: "--apply", kind: "bool", label: "Remove interim and empty fields", primary: true, mutating: true },
      { flag: "--known-fields", kind: "text", label: "Accept extra field names", placeholder: "code,pdf" },
      { flag: "--strict", kind: "bool", label: "Exit non-zero if anything is found" },
    ],
  },
  {
    id: "check-missing",
    group: "Quality checks",
    label: "check missing",
    summary: "Report entries that lack required fields (month by default).",
    argv: ["check", "missing", "input.bib"],
    options: [
      { flag: "--fields", kind: "text", label: "Required fields", placeholder: "month,publisher", primary: true },
      { flag: "--entry-types", kind: "text", label: "Entry types", placeholder: "inproceedings,article" },
      { flag: "--strict", kind: "bool", label: "Exit non-zero if anything is found" },
    ],
  },
  {
    id: "check-editions",
    group: "Quality checks",
    label: "check editions",
    summary: "Report the fields of the venue's schema that entries lack.",
    argv: ["check", "editions", "input.bib"],
    needs: ["venues"],
    options: [
      { flag: "--learn", kind: "bool", label: "Write the schemas it finds into the library", primary: true },
      { flag: "--ignore-fields", kind: "text", label: "Ignore fields", placeholder: "timestamp,biburl" },
      { flag: "--include-fields", kind: "text", label: "Include fields", placeholder: "doi,pages" },
      { flag: "--strict", kind: "bool", label: "Exit non-zero if anything is found" },
    ],
  },
  {
    id: "check-venues",
    group: "Quality checks",
    label: "check venues",
    summary: "Check the venue library itself for missing and inconsistent fields.",
    argv: ["check", "venues"],
    needs: ["venues"],
    options: [
      { flag: "--journal-fields", kind: "text", label: "Journal fields", placeholder: "publisher,issn" },
      { flag: "--proceedings-fields", kind: "text", label: "Proceedings fields", placeholder: "venue,publisher,month" },
      { flag: "--apply", kind: "bool", label: "Write the fixes into the library", mutating: true },
    ],
  },
  {
    id: "venues-where",
    group: "Inspect the runtime",
    label: "venues where",
    summary: "Show which venue libraries apply, and how many records they hold.",
    argv: ["venues", "where"],
  },
  {
    id: "venues-providers",
    group: "Inspect the runtime",
    label: "venues providers",
    summary: "Show where bibcc finds each conference's official BibTeX.",
    argv: ["venues", "providers"],
  },
  {
    id: "config-where",
    group: "Inspect the runtime",
    label: "config where",
    summary: "Show every file that applies, and the format settings they give.",
    argv: ["config", "where"],
  },
  {
    id: "terms-list",
    group: "Inspect the runtime",
    label: "terms list",
    summary: "Print every protected term, with the scope of its file.",
    argv: ["terms", "list"],
  },
  {
    id: "version",
    group: "Inspect the runtime",
    label: "--version",
    summary: "Print the bundled bibcc version.",
    argv: ["--version"],
  },
];

// Commands that need the network or a local PDF library, so they stay in the CLI.
export const CLI_ONLY = [
  { label: "add", why: "downloads official BibTeX from CrossRef, arXiv, and publisher sites" },
  { label: "upgrade", why: "re-fetches the published version of a preprint" },
  { label: "check official", why: "downloads the official BibTeX again to compare" },
  { label: "complete --online", why: "resolves venues through CrossRef" },
  { label: "scholar", why: "queries Google Scholar, CrossRef, and Semantic Scholar" },
  { label: "librarian", why: "compares and renames the PDFs on your disk" },
  { label: "compose", why: "merges a whole directory tree of .bib files" },
];

// The offline checks, in the order the README's workflow lists them.
export const ALL_CHECKS = ["check-title", "check-quote", "check-keys", "check-fields", "check-missing", "check-editions"];

export const SAMPLE = `@inproceedings{Vaswani_Attention_NIPS2017,
  title={Attention is all you need},
  author={Vaswani, Ashish and Shazeer, Noam and Parmar, Niki and Uszkoreit, Jakob},
  booktitle={Advances in Neural Information Processing Systems},
  year={2017},
  pages={5998-6008}
}

@article{kingma2014adam,
  title={Adam: A method for stochastic optimization},
  author={Kingma, Diederik P and Ba, Jimmy},
  journal={arXiv preprint arXiv:1412.6980},
  year={2014},
  month={dec}
}

@inproceedings{He_ResNet_CVPR2016,
  title={Deep residual learning for image recognition},
  author={He, Kaiming and Zhang, Xiangyu and Ren, Shaoqing and Sun, Jian},
  booktitle={Proceedings of the IEEE conference on computer vision and pattern recognition},
  pages={770-778},
  year={2016},
  month={jun},
  doi={10.1109/CVPR.2016.90},
  timestamp={2017-05-23}
}
`;

export function byId(id) {
  return COMMANDS.find((command) => command.id === id);
}

// Turn a command and its chosen option values into the argv bibcc will see.
export function buildArgv(command, values) {
  const argv = ["bibcc", ...command.argv];
  for (const option of [...(command.options || []), ...(command.advanced || [])]) {
    const value = values[option.flag];
    if (option.kind === "bool") {
      if (value) argv.push(option.flag);
    } else if (option.kind === "tri") {
      if (value === "on") argv.push(option.flag);
      else if (value === "off") argv.push(option.neg);
    } else if (value !== undefined && value !== null && String(value).trim() !== "") {
      argv.push(option.flag, String(value).trim());
    }
  }
  return argv;
}

export function groups() {
  const order = [];
  const map = new Map();
  for (const command of COMMANDS) {
    if (!map.has(command.group)) {
      map.set(command.group, []);
      order.push(command.group);
    }
    map.get(command.group).push(command);
  }
  return order.map((name) => ({ name, commands: map.get(name) }));
}

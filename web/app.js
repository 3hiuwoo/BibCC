import { CLI_ONLY, ALL_CHECKS, SAMPLE, byId, buildArgv, groups } from "./commands.js";

const $ = (id) => document.getElementById(id);

const el = {
  status: $("status"), statusText: $("statusText"),
  bib: $("bib"), stats: $("stats"),
  venues: $("venues"), terms: $("terms"), config: $("config"),
  profileHint: $("profileHint"),
  command: $("command"), run: $("run"), commandSummary: $("commandSummary"),
  options: $("options"), runNote: $("runNote"),
  custom: $("custom"), runCustom: $("runCustom"), cliOnly: $("cliOnly"),
  console: $("console"), consoleMeta: $("consoleMeta"),
  result: $("result"), resultBadge: $("resultBadge"),
  reportList: $("reportList"), reportBody: $("reportBody"),
  reportMeta: $("reportMeta"), reportsBadge: $("reportsBadge"),
  footVersion: $("footVersion"),
};

const state = {
  ready: false,
  busy: false,
  pasted: "",
  reports: [],
  selectedReport: null,
  resultView: "bib",
  totalDiff: "",
  values: new Map(),
};

// ---------------------------------------------------------------- runtime

const worker = new Worker(new URL("bibcc-worker.js", import.meta.url), { type: "module" });
const pending = new Map();
let sequence = 0;

function request(type, payload) {
  return new Promise((resolve, reject) => {
    const id = ++sequence;
    pending.set(id, { resolve, reject });
    worker.postMessage({ type, id, ...payload });
  });
}

worker.onmessage = (event) => {
  const message = event.data;
  if (message.type === "result") {
    const entry = pending.get(message.id);
    if (!entry) return;
    pending.delete(message.id);
    if (message.ok) entry.resolve(message);
    else entry.reject(new Error(message.error));
    return;
  }
  if (message.type === "progress") {
    setStatus("booting", `${message.stage}…`);
    return;
  }
  if (message.type === "ready") {
    state.ready = true;
    el.footVersion.textContent = message.bibccVersion;
    setStatus("ready", `bibcc ${message.bibccVersion} ready`);
    setBusy(false);
    return;
  }
  if (message.type === "error") {
    setStatus("error", "Runtime failed to start");
    printLine(`The Python runtime did not start: ${message.error}`, "err");
    printLine("The usual cause is a blocked CDN (jsDelivr) or a browser extension. To try again, reload the page.", "dim");
  }
};

function setStatus(kind, text) {
  el.status.querySelector(".dot").dataset.state = kind;
  el.statusText.textContent = text;
}

// ---------------------------------------------------------------- console

function lineNode(text, className) {
  const node = document.createElement("div");
  if (className) node.className = className;
  node.textContent = text;
  return node;
}

function diffClass(line) {
  if (line.startsWith("+")) return "diff-line add";
  if (line.startsWith("-")) return "diff-line del";
  if (line.startsWith("@")) return "diff-line hunk";
  return "diff-line dim";
}

function lines(text) {
  return text.replace(/\n$/, "").split("\n");
}

function printLine(text, className) {
  el.console.appendChild(lineNode(text, className));
  el.console.scrollTop = el.console.scrollHeight;
}

function printBlock(text, className) {
  for (const line of lines(text || "")) printLine(line, className);
}

function printDiffInto(container, diff) {
  for (const line of lines(diff)) container.appendChild(lineNode(line, diffClass(line)));
}

function printExit(code, changed) {
  const ok = code === 0;
  printLine(ok ? `exit 0${changed ? " · the file changed" : ""}` : `exit ${code}`, ok ? "dim" : "err");
  printLine("", "rule");
}

// ---------------------------------------------------------------- running

function syncPayload() {
  return {
    bib: el.bib.value,
    venues: el.venues.value,
    terms: el.terms.value,
    config: el.config.value,
  };
}

async function runArgv(argv) {
  if (!state.ready) {
    printLine("The runtime is still starting.", "err");
    return null;
  }
  const offline = networkReason(argv);
  if (offline) {
    printLine(`$ ${argv.join(" ")}`, "cmd");
    printLine(`This command ${offline}, which a browser tab can't do. Run it in the terminal.`, "err");
    printLine("", "rule");
    return null;
  }
  setStatus("busy", `Running ${argv.slice(1).join(" ") || "--version"}…`);
  setBusy(true);
  printLine(`$ ${argv.join(" ")}`, "cmd");
  try {
    await request("sync", { files: syncPayload() });
    const result = await request("run", { argv });
    printBlock(result.stdout);
    if (result.stderr) printBlock(result.stderr, "err");
    if (result.diff) {
      printLine("--- what changed ---", "dim");
      printDiffInto(el.console, result.diff);
    }
    printExit(result.code, result.changed);
    applyResult(result);
    return result;
  } catch (error) {
    printLine(String(error.message || error), "err");
    printExit(-1, false);
    return null;
  } finally {
    setBusy(false);
    setStatus("ready", `bibcc ${el.footVersion.textContent} ready`);
  }
}

// Every button that starts a run, so a second run can't interleave with the first.
const RUN_BUTTONS = ["run", "runCustom", "runAllChecks", "runFormat", "runPipeline", "resetRuntime"];

function setBusy(busy) {
  state.busy = busy;
  for (const id of RUN_BUTTONS) $(id).disabled = busy || !state.ready;
}

// The reason a command can't run here, or "" if it can. Mirrors CLI_ONLY.
function networkReason(argv) {
  const args = argv[0] === "bibcc" ? argv.slice(1) : argv;
  const words = args.filter((arg) => !arg.startsWith("-")).slice(0, 2).join(" ");
  if (args.includes("--online")) return CLI_ONLY.find((item) => item.label === "complete --online").why;
  const item = CLI_ONLY.find((entry) => words === entry.label || words.startsWith(entry.label + " "));
  return item ? item.why : "";
}

function applyResult(result) {
  if (result.bib !== undefined && result.bib !== el.bib.value) {
    el.bib.value = result.bib;
    refreshStats(false);
  }
  const support = result.support || {};
  for (const key of ["venues", "terms", "config"]) {
    if (support[key] !== undefined && support[key] !== el[key].value) {
      el[key].value = support[key];
      printLine(`bibcc updated ${key === "venues" ? "venues.yaml" : key === "terms" ? "terms.txt" : "config.yaml"} under Supporting files.`, "dim");
    }
  }
  state.reports = result.reports || [];
  renderReports();
  refreshTotalDiff();
}

async function refreshTotalDiff() {
  const changed = el.bib.value !== state.pasted;
  el.resultBadge.hidden = !changed;
  if (!changed || state.resultView !== "diff") {
    if (state.resultView === "diff") renderResult();
    return;
  }
  try {
    state.totalDiff = (await request("diff", { text: state.pasted })).diff || "";
  } catch {
    state.totalDiff = "";
  }
  renderResult();
}

async function runSequence(argvLists) {
  if (state.busy) return;
  el.console.textContent = "";
  for (const argv of argvLists) await runArgv(argv);
  el.consoleMeta.textContent = `${argvLists.length} commands · ${new Date().toLocaleTimeString()}`;
}

// ---------------------------------------------------------------- options UI

const valueKey = (commandId, flag) => `${commandId}\u0000${flag}`;

function optionValue(command, option) {
  const key = valueKey(command.id, option.flag);
  if (!state.values.has(key)) {
    state.values.set(key, option.kind === "bool" ? option.defaultOn === true : "");
  }
  return state.values.get(key);
}

function optionValues(command) {
  const values = {};
  for (const option of allOptions(command)) values[option.flag] = optionValue(command, option);
  return values;
}

const allOptions = (command) => [...(command.options || []), ...(command.advanced || [])];

function buildOption(command, option) {
  const row = document.createElement("div");
  row.className = "opt" + (option.primary ? " primary" : "");
  const key = valueKey(command.id, option.flag);
  const value = optionValue(command, option);
  const label = document.createElement("label");
  const caption = document.createElement("span");
  caption.textContent = option.label;

  let control;
  if (option.kind === "bool") {
    control = document.createElement("input");
    control.type = "checkbox";
    control.checked = value === true;
    control.addEventListener("change", () => state.values.set(key, control.checked));
  } else if (option.kind === "tri") {
    control = document.createElement("select");
    for (const [value2, text] of [["", "default"], ["on", "on"], ["off", "off"]]) {
      const choice = document.createElement("option");
      choice.value = value2;
      choice.textContent = text;
      control.appendChild(choice);
    }
    control.value = value;
    control.addEventListener("change", () => state.values.set(key, control.value));
  } else {
    control = document.createElement("input");
    control.type = option.kind === "number" ? "number" : "text";
    control.placeholder = option.placeholder || "";
    if (option.kind === "number") control.min = "0";
    control.value = value;
    control.addEventListener("input", () => state.values.set(key, control.value));
  }

  label.append(control, caption);
  if (option.kind !== "bool" && option.kind !== "tri") label.replaceChildren(caption, control);
  const flag = document.createElement("code");
  flag.className = "flag";
  flag.textContent = option.kind === "tri" ? `${option.flag} / ${option.neg}` : option.flag;
  row.append(label, flag);

  if (option.hint) {
    const hint = document.createElement("span");
    hint.className = "hint";
    hint.textContent = option.hint;
    row.appendChild(hint);
  }
  return row;
}

const currentCommand = () => byId(el.command.value);

function renderOptions() {
  const command = currentCommand();
  el.options.textContent = "";
  if (!command) return;
  for (const option of command.options || []) el.options.appendChild(buildOption(command, option));
  if (command.advanced?.length) {
    const box = document.createElement("details");
    box.className = "more-options";
    const summary = document.createElement("summary");
    summary.textContent = `More options (${command.advanced.length})`;
    const inner = document.createElement("div");
    inner.className = "options";
    for (const option of command.advanced) inner.appendChild(buildOption(command, option));
    box.append(summary, inner);
    el.options.appendChild(box);
  }
  el.commandSummary.textContent = command.summary || "";
  el.runNote.textContent = command.needs?.includes("venues") && !el.venues.value.trim()
    ? "This command reads the venue library, which is empty. To add one, open Supporting files."
    : "Commands run against the file in Your bibliography.";
}

function buildCommandSelect() {
  for (const group of groups()) {
    const optgroup = document.createElement("optgroup");
    optgroup.label = group.name;
    for (const command of group.commands) {
      const option = document.createElement("option");
      option.value = command.id;
      option.textContent = command.label;
      optgroup.appendChild(option);
    }
    el.command.appendChild(optgroup);
  }
  el.command.value = "format";
}

function renderCliOnly() {
  for (const item of CLI_ONLY) {
    const li = document.createElement("li");
    const code = document.createElement("code");
    code.textContent = item.label;
    li.append(code, document.createTextNode(`: ${item.why}`));
    el.cliOnly.appendChild(li);
  }
}

// ---------------------------------------------------------------- tabs and result

function selectTab(name) {
  for (const button of document.querySelectorAll(".tabs [role=tab]")) {
    const active = button.dataset.tab === name;
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
    $(`tab-${button.dataset.tab}`).hidden = !active;
  }
  if (name === "result") renderResult();
}

function renderResult() {
  el.result.textContent = "";
  if (state.resultView === "diff") {
    if (state.totalDiff) printDiffInto(el.result, state.totalDiff);
    else el.result.appendChild(lineNode("No difference from what you pasted.", "dim"));
    return;
  }
  el.result.textContent = el.bib.value || "(empty)";
}

function renderReports() {
  el.reportList.textContent = "";
  el.reportsBadge.hidden = state.reports.length === 0;
  el.reportsBadge.textContent = String(state.reports.length);

  if (state.reports.length === 0) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "bibcc writes its reports here: diffs, missing fields, title case, and key and field issues.";
    el.reportList.appendChild(li);
    state.selectedReport = null;
    el.reportBody.textContent = "";
    el.reportMeta.textContent = "No report selected.";
    return;
  }

  const selected = state.reports.find((report) => report.path === state.selectedReport) || state.reports[0];
  state.selectedReport = selected.path;
  for (const report of state.reports) {
    const li = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = report.path;
    button.setAttribute("aria-current", String(report === selected));
    button.addEventListener("click", () => {
      state.selectedReport = report.path;
      renderReports();
    });
    li.appendChild(button);
    el.reportList.appendChild(li);
  }
  el.reportBody.textContent = selected.text || "(empty)";
  el.reportMeta.textContent =
    `${selected.path} · ${selected.size.toLocaleString()} bytes${selected.truncated ? " · truncated" : ""}`;
}

// ---------------------------------------------------------------- input handling

function refreshStats(rebaseline) {
  const text = el.bib.value;
  const count = (text.match(/^@[a-zA-Z]+\s*\{/gm) || []).length;
  el.stats.textContent = text.trim()
    ? `${count} ${count === 1 ? "entry" : "entries"} · ${text.length.toLocaleString()} chars`
    : "No entries yet";
  if (rebaseline) state.pasted = text;
  $("revert").disabled = text === state.pasted;
  el.resultBadge.hidden = text === state.pasted;
  if (state.resultView === "bib" && !$("tab-result").hidden) renderResult();
}

function setBib(text) {
  el.bib.value = text;
  state.pasted = text;
  refreshStats(true);
  refreshTotalDiff();
}

async function loadProfile() {
  el.profileHint.textContent = "Loading…";
  const targets = [
    ["data/miaa.venues.yaml", el.venues],
    ["data/miaa.terms.txt", el.terms],
    ["data/miaa.config.yaml", el.config],
  ];
  let venues = 0;
  for (const [path, target] of targets) {
    try {
      const response = await fetch(path);
      if (!response.ok) throw new Error(String(response.status));
      target.value = await response.text();
    } catch (error) {
      el.profileHint.textContent = `Could not load ${path} (${error.message}).`;
      return;
    }
  }
  venues = (el.venues.value.match(/^- name:/gm) || []).length;
  el.profileHint.textContent = `Loaded the miaa profile: ${venues} venue records.`;
  $("support").open = true;
  renderOptions();
}

async function copy(text, button) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const helper = document.createElement("textarea");
    helper.value = text;
    document.body.appendChild(helper);
    helper.select();
    document.execCommand("copy");
    helper.remove();
  }
  const original = button.textContent;
  button.textContent = "Copied";
  setTimeout(() => { button.textContent = original; }, 1200);
}

function download(text) {
  const url = URL.createObjectURL(new Blob([text], { type: "application/x-bibtex" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "references.bib";
  link.click();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------- wiring

buildCommandSelect();
renderCliOnly();
renderOptions();
renderReports();
refreshStats(true);
setBusy(false);
worker.postMessage({ type: "init" });

el.command.addEventListener("change", renderOptions);

el.run.addEventListener("click", () => {
  if (state.busy) return;
  const command = currentCommand();
  if (command) runArgv(buildArgv(command, optionValues(command)));
});

el.runCustom.addEventListener("click", () => {
  if (state.busy) return;
  const argv = el.custom.value.trim().split(/\s+/).filter(Boolean);
  if (argv.length) runArgv(argv[0] === "bibcc" ? argv : ["bibcc", ...argv]);
});
el.custom.addEventListener("keydown", (event) => {
  if (event.key === "Enter") el.runCustom.click();
});

$("runAllChecks").addEventListener("click", () =>
  runSequence(ALL_CHECKS.map((id) => ["bibcc", ...byId(id).argv])));
$("runFormat").addEventListener("click", () =>
  runSequence([["bibcc", "format", "input.bib", "--in-place"]]));
$("runPipeline").addEventListener("click", () => runSequence([
  ["bibcc", "format", "input.bib", "--in-place"],
  ["bibcc", "check", "title", "input.bib", "--apply"],
  ["bibcc", "check", "fields", "input.bib", "--apply"],
]));

$("resetRuntime").addEventListener("click", async () => {
  if (!state.ready || state.busy) return;
  const result = await request("reset", {});
  state.reports = result.reports || [];
  state.selectedReport = null;
  renderReports();
  printLine("Cleared the reports bibcc had written.", "dim");
});

$("loadSample").addEventListener("click", () => setBib(SAMPLE));
$("openFile").addEventListener("click", () => $("filePicker").click());
$("filePicker").addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  setBib(await file.text());
  event.target.value = "";
});
$("revert").addEventListener("click", () => setBib(state.pasted));
$("clearInput").addEventListener("click", () => setBib(""));

$("loadProfile").addEventListener("click", loadProfile);
$("clearProfile").addEventListener("click", () => {
  el.venues.value = "";
  el.terms.value = "";
  el.config.value = "";
  el.profileHint.textContent = "Cleared.";
  renderOptions();
});

for (const button of document.querySelectorAll(".tabs [role=tab]")) {
  button.addEventListener("click", () => selectTab(button.dataset.tab));
  button.addEventListener("keydown", (event) => {
    const buttons = [...document.querySelectorAll(".tabs [role=tab]")];
    const index = buttons.indexOf(button);
    const next = event.key === "ArrowRight" ? buttons[(index + 1) % buttons.length]
      : event.key === "ArrowLeft" ? buttons[(index - 1 + buttons.length) % buttons.length]
      : null;
    if (next) {
      event.preventDefault();
      next.focus();
      selectTab(next.dataset.tab);
    }
  });
}

for (const button of document.querySelectorAll(".seg")) {
  button.addEventListener("click", () => {
    for (const other of document.querySelectorAll(".seg")) {
      const active = other === button;
      other.classList.toggle("active", active);
      other.setAttribute("aria-pressed", String(active));
    }
    state.resultView = button.dataset.view;
    refreshTotalDiff();
    renderResult();
  });
}

el.bib.addEventListener("input", () => refreshStats(true));

$("copyConsole").addEventListener("click", (event) => copy(el.console.textContent, event.currentTarget));
$("clearConsole").addEventListener("click", () => {
  el.console.textContent = "";
  el.consoleMeta.textContent = "Cleared.";
});
$("copyResult").addEventListener("click", (event) => copy(el.bib.value, event.currentTarget));
$("downloadResult").addEventListener("click", () => download(el.bib.value));
$("copyReport").addEventListener("click", (event) => copy(el.reportBody.textContent, event.currentTarget));

selectTab("console");

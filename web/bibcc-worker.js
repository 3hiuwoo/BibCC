// Runs bibcc inside Pyodide. Everything stays in this worker's in-memory filesystem:
// no bibliography is uploaded anywhere.
const PYODIDE_CDN = "https://cdn.jsdelivr.net/pyodide/v0.29.0/full/";
const BUNDLE_URL = new URL("vendor/bibcc-bundle.zip", self.location.href);

// The driver runs each command against a clean bibcc import, captures stdout/stderr,
// and reports back the rewritten file, a diff, and whatever bibcc wrote to .bibcc/.
// stdin always answers "q" so an accidental --interactive run quits instead of hanging.
const DRIVER = `
import sys, os, io, traceback, difflib, shutil

os.environ["HOME"] = "/home/user"
os.environ.pop("XDG_CONFIG_HOME", None)
sys.path.insert(0, "/bundle")

WORK = "/work"
BIB = WORK + "/input.bib"
CONF = "/home/user/.config/bibcc"
REPORT_ROOT = WORK + "/.bibcc"
MAX_REPORT = 300_000
MAX_REPORTS = 60


class QuitStdin(io.TextIOBase):
    def readline(self, *args):
        return "q\\n"

    def read(self, *args):
        return ""


def _purge():
    for name in [k for k in list(sys.modules) if k == "bibcc" or k.startswith("bibcc.")]:
        del sys.modules[name]


def _write(path, text):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text or "")


def setup():
    os.makedirs(WORK, exist_ok=True)
    os.makedirs(CONF, exist_ok=True)
    os.chdir(WORK)
    _purge()
    import bibcc
    return bibcc.__version__


FILES = {
    "bib": BIB,
    "venues": CONF + "/venues.yaml",
    "terms": CONF + "/terms.txt",
    "config": CONF + "/config.yaml",
}


def sync(files):
    for key, text in files.items():
        if key in FILES and text is not None:
            _write(FILES[key], text)


def read_support():
    # Commands such as complete --update-venues, check editions --learn, and terms add
    # write the user library, so the page reads it back after each run.
    found = {}
    for key in ("venues", "terms", "config"):
        try:
            with open(FILES[key], encoding="utf-8") as fh:
                found[key] = fh.read()
        except OSError:
            found[key] = ""
    return found


def reset():
    for name in os.listdir(WORK):
        if name == "input.bib":
            continue
        path = WORK + "/" + name
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            os.remove(path)


def read_bib():
    try:
        with open(BIB, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def collect_reports():
    found = []
    if not os.path.isdir(REPORT_ROOT):
        return found
    for dirpath, dirnames, filenames in os.walk(REPORT_ROOT):
        dirnames.sort()
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, WORK).replace(os.sep, "/")
            try:
                size = os.path.getsize(full)
                with open(full, encoding="utf-8", errors="replace") as fh:
                    text = fh.read(MAX_REPORT)
            except OSError:
                continue
            found.append({"path": rel, "size": size, "text": text, "truncated": size > len(text)})
            if len(found) >= MAX_REPORTS:
                return found
    return found


def run(argv):
    before = read_bib()
    out_buf, err_buf = io.StringIO(), io.StringIO()
    saved = sys.stdout, sys.stderr, sys.stdin, sys.argv
    sys.stdout, sys.stderr, sys.stdin, sys.argv = out_buf, err_buf, QuitStdin(), list(argv)
    code = 0
    try:
        _purge()
        import bibcc.cli
        bibcc.cli.main()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    except BaseException:
        err_buf.write(traceback.format_exc())
        code = -1
    finally:
        sys.stdout, sys.stderr, sys.stdin, sys.argv = saved
    after = read_bib()
    diff = "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile="before this command", tofile="after this command")) if before != after else ""
    return {
        "code": code,
        "stdout": out_buf.getvalue(),
        "stderr": err_buf.getvalue(),
        "bib": after,
        "changed": before != after,
        "diff": diff,
        "reports": collect_reports(),
        "support": read_support(),
    }


def diff_against(text):
    current = read_bib()
    if text == current:
        return ""
    return "".join(difflib.unified_diff(
        (text or "").splitlines(keepends=True), current.splitlines(keepends=True),
        fromfile="as pasted", tofile="current"))
`;

let pyodide = null;

function send(type, payload) {
  self.postMessage({ type, ...payload });
}

async function init() {
  send("progress", { stage: "Loading the Python runtime", detail: "Pyodide from jsDelivr" });
  const { loadPyodide } = await import(PYODIDE_CDN + "pyodide.mjs");
  pyodide = await loadPyodide({ indexURL: PYODIDE_CDN });

  send("progress", { stage: "Loading PyYAML, pyparsing, and ssl", detail: "what bibcc imports" });
  // bibcc/sources.py imports ssl, and bibcc.formatter reaches it through adder -> completer ->
  // crosscheck, so even the offline commands need it. Pyodide 0.29 ships ssl as a package.
  await pyodide.loadPackage(["pyyaml", "pyparsing", "ssl"]);

  send("progress", { stage: "Unpacking bibcc", detail: "fetching the bundled sources" });
  const response = await fetch(BUNDLE_URL);
  if (!response.ok) throw new Error(`cannot fetch ${BUNDLE_URL.pathname} (${response.status})`);
  pyodide.unpackArchive(new Uint8Array(await response.arrayBuffer()), "zip", { extractDir: "/bundle" });

  pyodide.FS.mkdirTree("/work");
  pyodide.FS.mkdirTree("/home/user/.config/bibcc");
  pyodide.runPython(DRIVER);
  send("ready", { bibccVersion: pyodide.globals.get("setup")() || "", pyodideVersion: pyodide.version });
}

function call(name, ...args) {
  const fn = pyodide.globals.get(name);
  // Plain JS objects stay proxies in Python, so convert them: sync() needs a real dict
  // and run() needs a real list.
  const result = fn(...args.map((arg) => pyodide.toPy(arg)));
  return result && typeof result.toJs === "function"
    ? result.toJs({ dict_converter: Object.fromEntries })
    : result;
}

async function handle(message) {
  const reply = (payload) => send("result", { id: message.id, ...payload });
  try {
    switch (message.type) {
      case "sync":
        call("sync", message.files);
        reply({ ok: true });
        break;
      case "run": {
        const result = call("run", message.argv);
        reply({ ok: true, ...result });
        break;
      }
      case "reset":
        call("reset");
        reply({ ok: true, reports: call("collect_reports") });
        break;
      case "reports":
        reply({ ok: true, reports: call("collect_reports") });
        break;
      case "diff":
        reply({ ok: true, diff: call("diff_against", message.text) });
        break;
      default:
        reply({ ok: false, error: `unknown message type ${message.type}` });
    }
  } catch (error) {
    reply({ ok: false, error: String(error && error.message ? error.message : error) });
  }
}

self.onmessage = async (event) => {
  const message = event.data;
  if (message.type === "init") {
    try {
      await init();
    } catch (error) {
      send("error", { error: String(error && error.message ? error.message : error) });
    }
    return;
  }
  if (!pyodide) {
    send("result", { id: message.id, ok: false, error: "the runtime is still starting" });
    return;
  }
  await handle(message);
};

self.postMessage({ type: "loaded" });

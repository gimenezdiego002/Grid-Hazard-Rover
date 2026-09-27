/* Per-tab virtual state. Runs the exact reviewed Python engines without a server. */
const SOURCES = Object.freeze(["simulator.py", "arm_simulator.py", "arm_handoff.py"]);
const MAX_REQUEST_CHARS = 65536;

const DISPATCH_CODE = `
import json
from relay_gateway.simulator import Simulator, SimulatorConflict
from relay_gateway.arm_simulator import ArmSimulator, ArmSimulatorConflict

_relay_fleet = Simulator()
_relay_arm = ArmSimulator()

def _relay_dispatch(request_json):
    try:
        request = json.loads(request_json)
        if type(request) is not dict or set(request) != {"path", "method", "body"}:
            raise ValueError("Invalid simulator request envelope")
        path, method, body = request["path"], request["method"], request["body"]
        routes = {
            "/api/simulator": (_relay_fleet, "GET"),
            "/api/simulator/actions": (_relay_fleet, "POST"),
            "/api/simulator/arm": (_relay_arm, "GET"),
            "/api/simulator/arm/actions": (_relay_arm, "POST"),
        }
        if type(path) is not str or path not in routes:
            return json.dumps({"status": 404, "body": {"detail": "Unknown simulator route"}})
        engine, expected_method = routes[path]
        if method != expected_method:
            return json.dumps({"status": 405, "body": {"detail": "Method not supported for this simulator route"}})
        if method == "GET":
            if body is not None:
                raise ValueError("Snapshot reads do not accept a body")
            result = engine.snapshot()
        else:
            if type(body) is not dict or not {"run_id", "action_id", "action"}.issubset(body):
                raise ValueError("Actions require run_id, action_id, and action")
            if any(type(body[k]) is not str for k in ("run_id", "action_id", "action")):
                raise ValueError("Action identifiers must be strings")
            result = engine.apply(**body)
        result["runtime"] = "browser_pyodide"
        result["storage"] = "browser_tab_memory"
        result["session_scope"] = "this_browser_tab_until_reload"
        return json.dumps({"status": 200, "body": result}, allow_nan=False)
    except (SimulatorConflict, ArmSimulatorConflict) as error:
        return json.dumps({"status": 409, "body": {"detail": str(error)}})
    except (ValueError, TypeError) as error:
        return json.dumps({"status": 400, "body": {"detail": str(error)}})
    except Exception:
        return json.dumps({"status": 500, "body": {"detail": "Virtual simulator failed; refresh its current state before continuing"}})
`;

/** Dependency injection permits real-Pyodide Node tests without browser mocks. */
export async function initializeSimulator(loadPyodide, readSource, runtimeOptions = {}) {
  const pyodide = await loadPyodide(runtimeOptions);
  pyodide.FS.mkdirTree("/home/pyodide/relay_gateway");
  pyodide.FS.writeFile("/home/pyodide/relay_gateway/__init__.py", "", {encoding: "utf8"});
  const sources = await Promise.all(SOURCES.map(async (name) => [name, await readSource(name)]));
  for (const [name, source] of sources) {
    if (typeof source !== "string" || source.length > 131072) throw new Error("Invalid bundled simulator source");
    pyodide.FS.writeFile(`/home/pyodide/relay_gateway/${name}`, source, {encoding: "utf8"});
  }
  pyodide.runPython("import sys\nsys.path.insert(0, '/home/pyodide')");
  pyodide.runPython(DISPATCH_CODE);
  const dispatchPython = pyodide.globals.get("_relay_dispatch");
  return {
    dispatch(request) {
      if (!request || typeof request !== "object" || Array.isArray(request)) {
        return {status: 400, body: {detail: "Invalid simulator request"}};
      }
      let encoded;
      try {
        encoded = JSON.stringify({path: request.path, method: request.method, body: request.body ?? null});
      } catch (_) {
        return {status: 400, body: {detail: "Simulator request must contain JSON data"}};
      }
      if (encoded.length > MAX_REQUEST_CHARS) return {status: 400, body: {detail: "Simulator request exceeds the size limit"}};
      return JSON.parse(dispatchPython(encoded));
    },
    dispose() { dispatchPython.destroy(); },
    version: pyodide.version,
  };
}

async function bootWorker() {
  self.postMessage({type: "status", message: "Loading the private browser simulation runtime…"});
  let bootError = null;
  const ready = (async () => {
    const {loadPyodide} = await import(new URL("./runtime/pyodide.mjs", import.meta.url).href);
    const runtime = await initializeSimulator(loadPyodide, async (name) => {
      const response = await fetch(new URL(`./python/relay_gateway/${name}`, import.meta.url));
      if (!response.ok) throw new Error(`Bundled simulator source is unavailable (${response.status})`);
      return response.text();
    }, {indexURL: new URL("./runtime/", import.meta.url).href});
    self.postMessage({type: "ready", version: runtime.version});
    return runtime;
  })().catch((error) => {
    bootError = error;
    self.postMessage({type: "error", message: "Unable to load the browser simulator. Reload the page to try again."});
    return null;
  });

  // One queue owns both scenes; concurrent frontend controls cannot reenter Python.
  let queue = Promise.resolve();
  self.onmessage = ({data}) => {
    if (!data || data.type !== "request" || !["string", "number"].includes(typeof data.id)) return;
    queue = queue.then(async () => {
      const runtime = await ready;
      const result = bootError || !runtime
        ? {status: 503, body: {detail: "Browser simulator is unavailable; reload the page"}}
        : runtime.dispatch({path: data.path, method: data.method, body: data.body});
      self.postMessage({type: "response", id: data.id, ...result});
    }).catch(() => {
      self.postMessage({type: "response", id: data.id, status: 500,
                        body: {detail: "Browser simulator request failed; read the current scene before continuing"}});
    });
  };
}

if (typeof self !== "undefined" && typeof self.postMessage === "function") void bootWorker();

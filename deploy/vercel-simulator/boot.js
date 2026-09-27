// Only the four simulator routes execute in the dedicated, tab-local worker.
export function createFetchBridge({worker, nativeFetch, origin, onFatal = () => {}}) {
  const routes = new Map([["/api/simulator", "GET"], ["/api/simulator/actions", "POST"], ["/api/simulator/arm", "GET"], ["/api/simulator/arm/actions", "POST"]]);
  const pending = new Map();
  let sequence = 0, closed = false;
  const abortError = () => new DOMException("The request was aborted.", "AbortError");
  function failAll(message) {
    closed = true;
    for (const request of pending.values()) {request.cleanup();request.reject(new Error(message));}
    pending.clear();
  }
  function onMessage(event) {
    const message = event.data;
    if (message?.type === "error" && !message.id) {
      failAll(message.message || "The browser simulation worker failed.");onFatal(message.message);return;
    }
    if (message?.type !== "response") return;
    const request = pending.get(message.id);
    if (!request) return; // A timed-out mutation may finish; never repeat it here.
    pending.delete(message.id);request.cleanup();
    if (!Number.isInteger(message.status) || message.status < 200 || message.status > 599 || message.body === undefined) {
      request.reject(new Error("Invalid response from browser simulation worker."));return;
    }
    try {request.resolve(new Response(JSON.stringify(message.body), {status: message.status, headers: {"Content-Type": "application/json; charset=utf-8", "X-Relay-Execution": "browser-worker"}}));}
    catch (_) {request.reject(new Error("Invalid response from browser simulation worker."));}
  }
  function onError(event) {
    const message = event.message || "The browser simulation worker stopped unexpectedly.";
    failAll(message);onFatal(message);
  }
  worker.addEventListener("message", onMessage);
  worker.addEventListener("error", onError);
  async function fetchBridge(input, options = {}) {
    const isRequest = typeof Request !== "undefined" && input instanceof Request;
    const url = new URL(isRequest ? input.url : String(input), origin);
    const method = String(options.method || (isRequest ? input.method : "GET")).toUpperCase();
    if (url.origin !== origin || url.search || routes.get(url.pathname) !== method) return nativeFetch(input, options);
    if (closed) throw new Error("The browser simulation worker is unavailable. Reload the simulator.");
    const signal = options.signal || (isRequest ? input.signal : undefined);
    if (signal?.aborted) throw abortError();
    let body = null;
    if (method === "POST") {
      const raw = options.body === undefined && isRequest ? await input.clone().text() : options.body;
      try {
        if (typeof raw !== "string" || raw.length > 32768) throw new Error("Invalid request body");
        body = JSON.parse(raw);
        if (!body || typeof body !== "object" || Array.isArray(body)) throw new Error("Invalid request body");
      } catch (_) {
        return new Response(JSON.stringify({detail: "Simulator actions require a JSON object of at most 32 KiB."}), {status: 400, headers: {"Content-Type": "application/json"}});
      }
    }
    if (signal?.aborted) throw abortError();
    return new Promise((resolve, reject) => {
      const id = `browser-request-${++sequence}`;
      const onAbort = () => {pending.delete(id);signal.removeEventListener("abort", onAbort);reject(abortError());};
      const cleanup = () => signal?.removeEventListener("abort", onAbort);
      pending.set(id, {resolve, reject, cleanup});
      signal?.addEventListener("abort", onAbort, {once: true});
      try {worker.postMessage({type: "request", id, method, path: url.pathname, body});}
      catch (error) {pending.delete(id);cleanup();reject(error);}
    });
  }
  return {fetch: fetchBridge, close() {worker.removeEventListener("message", onMessage);worker.removeEventListener("error", onError);failAll("Browser simulator closed.");}};
}

export async function bootstrap({window, document}) {
  const status = document.getElementById("browser-boot-status");
  const detail = document.getElementById("browser-boot-detail");
  const retry = document.getElementById("browser-boot-retry");
  const banner = document.getElementById("browser-boot");
  const nativeFetch = window.fetch.bind(window);
  let worker, bridge, timer, failed = false;
  retry.addEventListener("click", () => window.location.reload());
  const fail = (message) => {
    if (failed) return;
    failed = true;window.clearTimeout(timer);
    banner.classList.add("browser-boot-failed");
    status.textContent = "Browser simulator could not start or stopped.";
    detail.textContent = `${message || "Runtime unavailable."} Reload starts fresh tab-local simulations.`;
    retry.hidden = false;
    bridge?.close();worker?.terminate();
  };
  try {
    if (!window.Worker || !window.WebAssembly) throw new Error("This browser needs WebAssembly and module worker support.");
    status.textContent = "Preparing the browser simulation engine…";
    detail.textContent = "The first load downloads a local Python runtime. All mission computation then stays in this browser tab.";
    worker = new window.Worker("/worker.mjs", {type: "module"});
    bridge = createFetchBridge({worker, nativeFetch, origin: window.location.origin, onFatal: fail});
    window.fetch = bridge.fetch;
    await new Promise((resolve, reject) => {
      timer = window.setTimeout(() => reject(new Error("The runtime did not finish loading within 90 seconds.")), 90000);
      worker.addEventListener("message", (event) => {
        if (event.data?.type === "ready") {window.clearTimeout(timer);resolve();}
        else if (event.data?.type === "status") {detail.textContent = event.data.message;}
        else if (event.data?.type === "error") {reject(new Error(event.data.message || "Runtime initialization failed."));}
      });
      worker.addEventListener("error", (event) => reject(new Error(event.message || "Module worker failed to load.")), {once: true});
    });
    if (failed) return;
    // The existing controllers start only after WASM initialization. Their normal
    // request timeout therefore measures a simulation command, not a cold load.
    for (const path of ["/static/simulator.js", "/static/arm-simulator.js"]) {
      await new Promise((resolve, reject) => {
        const script = document.createElement("script");script.src = path;
        script.onload = resolve;script.onerror = () => reject(new Error(`Unable to load ${path}.`));
        document.head.append(script);
      });
    }
    banner.classList.add("browser-boot-ready");
    status.textContent = "Running entirely in this browser.";
    detail.textContent = "Each tab has its own simulated fleet and arm. Reloading resets both. No shared backend, hardware connection, or model calls.";
  } catch (error) {fail(error.message);}
}

if (typeof window !== "undefined" && typeof document !== "undefined") bootstrap({window, document});

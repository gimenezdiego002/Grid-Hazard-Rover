import assert from "node:assert/strict";
import test from "node:test";
import {readFile, readdir} from "node:fs/promises";
import {createHash} from "node:crypto";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {createFetchBridge, bootstrap} from "./boot.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const flush = () => new Promise(setImmediate);
class FakeWorker {
  constructor() {this.listeners = new Map();this.requests = [];this.terminated = false;}
  addEventListener(type, fn) {if (!this.listeners.has(type)) this.listeners.set(type, new Set());this.listeners.get(type).add(fn);}
  removeEventListener(type, fn) {this.listeners.get(type)?.delete(fn);}
  postMessage(message) {this.requests.push(message);}
  terminate() {this.terminated = true;}
  emit(type, event) {for (const fn of [...(this.listeners.get(type) || [])]) fn(event);}
  reply(index = 0, status = 200, body = {simulated: true}) {this.emit("message", {data: {type: "response", id: this.requests[index].id, status, body}});}
}
function bridge() {
  const worker = new FakeWorker(), nativeCalls = [], fatal = [];
  const adapter = createFetchBridge({worker, origin: "https://relay.example", nativeFetch: async (...args) => {nativeCalls.push(args);return new Response("native");}, onFatal: (message) => fatal.push(message)});
  return {worker, nativeCalls, fatal, ...adapter};
}
test("only exact same-origin simulator route and method pairs execute in the worker", async () => {
  const ui = bridge();
  for (const input of ["/api/simulator-extra", "/api/run", "https://elsewhere.example/api/simulator", "/api/simulator?other=1"]) await ui.fetch(input);
  await ui.fetch("/api/simulator", {method: "POST", body: "{}"});
  assert.equal(ui.nativeCalls.length, 5);assert.equal(ui.worker.requests.length, 0);
  const result = ui.fetch("/api/simulator");await flush();
  assert.deepEqual(ui.worker.requests[0], {type: "request", id: "browser-request-1", path: "/api/simulator", method: "GET", body: null});
  ui.worker.reply();assert.equal((await result).headers.get("X-Relay-Execution"), "browser-worker");ui.close();
});
test("all four intended routes preserve action fields and error status", async () => {
  const ui = bridge(), body = {run_id: "run-1", action_id: "action-1", action: "reset"};
  for (const [url, method] of [["/api/simulator", "GET"], ["/api/simulator/actions", "POST"], ["/api/simulator/arm", "GET"], ["/api/simulator/arm/actions", "POST"]]) {
    const response = ui.fetch(url, method === "POST" ? {method, body: JSON.stringify(body)} : {});await flush();
    const i = ui.worker.requests.length - 1;assert.equal(ui.worker.requests[i].path, url);assert.deepEqual(ui.worker.requests[i].body, method === "POST" ? body : null);
    ui.worker.reply(i, 409, {detail: "Stale run ID"});const reply = await response;assert.equal(reply.status, 409);assert.deepEqual(await reply.json(), {detail: "Stale run ID"});
  }
  ui.close();
});
test("Request objects work and invalid action bodies never reach the worker", async () => {
  const ui = bridge();
  for (const body of ["broken", "[]", "null", "x".repeat(32769)]) {const reply = await ui.fetch("/api/simulator/actions", {method: "POST", body});assert.equal(reply.status, 400);}
  assert.equal(ui.worker.requests.length, 0);
  const reply = ui.fetch(new Request("https://relay.example/api/simulator/arm/actions", {method: "POST", body: '{"action":"start"}'}));await flush();await flush();
  assert.deepEqual(ui.worker.requests[0].body, {action: "start"});ui.worker.reply();await reply;ui.close();
});
test("abort before dispatch does not mutate, and abort after dispatch never retries", async () => {
  const ui = bridge(), already = new AbortController();already.abort();
  await assert.rejects(ui.fetch("/api/simulator", {signal: already.signal}), {name: "AbortError"});assert.equal(ui.worker.requests.length, 0);
  const controller = new AbortController();const result = ui.fetch("/api/simulator/actions", {method: "POST", body: '{"action":"start"}', signal: controller.signal});await flush();
  controller.abort();await assert.rejects(result, {name: "AbortError"});ui.worker.reply(0);
  const read = ui.fetch("/api/simulator");await flush();ui.worker.reply(1, 200, {status: "running"});assert.equal((await (await read).json()).status, "running");
  assert.equal(ui.worker.requests.filter((request) => request.method === "POST").length, 1);ui.close();
});
test("worker failures reject pending and future owned requests while unrelated fetch remains native", async () => {
  const ui = bridge();const result = ui.fetch("/api/simulator");await flush();
  ui.worker.emit("error", {message: "WASM worker failed"});await assert.rejects(result, /WASM worker failed/);
  await assert.rejects(ui.fetch("/api/simulator/arm"), /unavailable/);await ui.fetch("/unrelated");assert.equal(ui.nativeCalls.length, 1);assert.equal(ui.fatal.length, 1);ui.close();
});
test("malformed worker responses reject without leaving a hanging UI request", async () => {
  const ui = bridge();const result = ui.fetch("/api/simulator");await flush();ui.worker.reply(0, 204, {notAllowed: true});await assert.rejects(result, /Invalid response/);ui.close();
});
test("boot waits for runtime readiness before loading either existing controller", async () => {
  const nodes = new Map(["browser-boot-status", "browser-boot-detail", "browser-boot-retry", "browser-boot"].map((id) => [id, {textContent: "", hidden: true, classList: {add() {}}, addEventListener() {}}]));
  const loaded = [];let worker;
  const window = {Worker: class extends FakeWorker {constructor() {super();worker = this;}}, WebAssembly: {}, fetch: async () => new Response("native"), location: {origin: "https://relay.example", reload() {}}, setTimeout: () => 1, clearTimeout() {}};
  const document = {getElementById: (id) => nodes.get(id), createElement: () => ({}), head: {append(script) {loaded.push(script.src);script.onload();}}};
  const boot = bootstrap({window, document});await flush();assert.deepEqual(loaded, []);
  worker.emit("message", {data: {type: "status", message: "Loading WASM"}});assert.equal(nodes.get("browser-boot-detail").textContent, "Loading WASM");
  worker.emit("message", {data: {type: "ready"}});await boot;
  assert.deepEqual(loaded, ["/static/simulator.js", "/static/arm-simulator.js"]);assert.match(nodes.get("browser-boot-status").textContent, /entirely in this browser/);
});
test("static build contains only approved code and exact engine copies, with no Mission lab link", async () => {
  const dist = path.join(here, "dist"), manifest = JSON.parse(await readFile(path.join(dist, "build-manifest.json")));
  assert.deepEqual((await readdir(path.join(dist, "python/relay_gateway"))).sort(), ["__init__.py", "arm_handoff.py", "arm_simulator.py", "simulator.py"]);
  for (const name of ["simulator.py", "arm_simulator.py", "arm_handoff.py"]) {
    const original = await readFile(path.join(here, "../../src/relay_gateway", name));
    assert.deepEqual(await readFile(path.join(dist, "python/relay_gateway", name)), original);
    assert.equal(manifest.source_sha256[name], createHash("sha256").update(original).digest("hex"));
  }
  const html = await readFile(path.join(dist, "index.html"), "utf8");assert.doesNotMatch(html, /Mission lab/);assert.match(html, /src="\/boot.js"/);assert.doesNotMatch(html, /script src="\/static\/(simulator|arm-simulator)\.js"/);
  assert.match(await readFile(path.join(dist, "runtime/PYODIDE-LICENSE"), "utf8"), /Mozilla Public License Version 2.0/);
  assert.match(await readFile(path.join(dist, "runtime/PYODIDE-NOTICE"), "utf8"), /Pyodide 314.0.7/);
  assert.match(html, /href="\/workflow-proof\.html">AI workflow/);
  assert.deepEqual((await readdir(dist)).sort(), ["boot.js", "build-manifest.json", "index.html", "licenses", "python", "runtime", "simulator.html", "static", "team-simulator-provenance.json", "worker.mjs", "workflow-proof.css", "workflow-proof.html"]);
});

test("teammate street scene shares the main page with an isolated static bundle and traced sources", async () => {
  const dist = path.join(here, "dist"), source = path.join(here, "../../web/team-simulator");
  const html = await readFile(path.join(dist, "index.html"), "utf8");
  assert.match(html, /id="street-simulator-root"/);
  assert.match(html, /href="#street-simulator"/);
  assert.match(html, /src="\/static\/team-simulator\/generated\/street\.js"/);
  assert.match(html, /href="\/static\/team-simulator\/style\.css"/);
  const manifest = JSON.parse(await readFile(path.join(dist, "build-manifest.json")));
  for (const [file, hash] of Object.entries(manifest.teammate_simulator.source_sha256)) {
    assert.equal(createHash("sha256").update(await readFile(path.join(source, file))).digest("hex"), hash);
  }
  const bundle = await readFile(path.join(dist, "static/team-simulator/generated/street.js"));
  assert.equal(bundle.length, manifest.teammate_simulator.javascript_bytes);
  assert.deepEqual(bundle, await readFile(path.join(source, "generated/street.js")));
  assert.deepEqual(await readFile(path.join(dist, "team-simulator-provenance.json")), await readFile(path.join(source, "provenance.json")));
  assert.deepEqual((await readdir(path.join(dist, "licenses"))).sort(), ["lucide-react.txt", "react-dom.txt", "react.txt", "scheduler.txt"]);
  assert.equal(manifest.teammate_simulator.physical_commands, 0);
  assert.equal(manifest.teammate_simulator.model_calls, 0);
});

test("workflow evidence stays static and publishes only artifact names and matching content hashes", async () => {
  const page = await readFile(path.join(here, "dist/workflow-proof.html"), "utf8");
  assert.doesNotMatch(page, /<script\b|https?:\/\/|ngrok-free|ngrok\.app|Bearer\s|\.state[\\/]/i);
  for (const file of ["jev-openjev-runtime.json", "jev-openjev-warmup.json", "jev-openjev-dry_monitoring.json", "jev-openjev-wet_episode.json", "jev-openjev-conflicting.json", "jev-openjev-ngrok-proof.json", "jev-comparison.json"]) {
    const bytes = await readFile(path.join(here, "../../artifacts", file));
    assert.ok(page.includes(file));assert.ok(page.includes(createHash("sha256").update(bytes).digest("hex")));
  }
  assert.match(page, /Gemini roles remained fixtures/);assert.match(page, /80 → 3 is a modeled request comparison/);assert.match(page, /do not demonstrate real cost savings/);
  const names = await readdir(path.join(here, "dist"));assert.ok(!names.includes("artifacts"));
});

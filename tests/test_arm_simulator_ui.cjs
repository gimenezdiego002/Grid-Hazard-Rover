// Finite virtual-arm controller checks; no browser, hardware, network, or model.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");
const source = fs.readFileSync(path.join(__dirname, "../web/arm-simulator.js"), "utf8");
const html = fs.readFileSync(path.join(__dirname, "../web/simulator.html"), "utf8");
const flush = () => new Promise(setImmediate);
const response = (data, status = 200) => ({ok: status < 400, status, json: async () => structuredClone(data)});
function snapshot(status = "idle", extra = {}) {
  const allowed = {idle: ["start", "pose", "capture", "replay", "reset"], running: ["step", "pause", "stop", "inject_fault", "reset"], paused: ["step", "resume", "capture", "stop", "reset"], faulted: ["clear_fault", "stop", "reset"], completed: ["start", "pose", "capture", "replay", "reset"], stopped: ["reset"]};
  return {run_id: "virtual-arm-1", status, stage: "home", simulated: true, source: "simulation", joints_deg: [90, 90, 90, 90, 90, 20], allowed_actions: allowed[status], elapsed_s: 0, routine: [], recorded_routine: [], current_waypoint: 0, progress: 0, gripper: {open_fraction: 1, state: "open"}, payload: {state: "at_source", position: {x: .35, y: 0, z: .15}}, link_positions: [{x: 0, y: 0, z: .1}, {x: 0, y: 0, z: .38}, {x: 0, y: 0, z: .62}, {x: 0, y: 0, z: .74}], events: [], ...extra};
}
async function page(initial = snapshot()) {
  const nodes = new Map();
  class Element {
    constructor() {this.children = [];this.listeners = {};this.style = {};this.value = "";this.textContent = "";}
    set id(value) {this._id = value;nodes.set(value, this);} get id() {return this._id;}
    append(...items) {this.children.push(...items);} replaceChildren(...items) {this.children = items;}
    addEventListener(name, fn) {this.listeners[name] = fn;}
    getBoundingClientRect() {return {width: 660, height: 330};}
  }
  for (const [, id] of html.matchAll(/\bid="([^"]+)"/g)) {const item = new Element();item.id = id;}
  const node = (id) => {assert.ok(nodes.has(id), `Missing ${id}`);return nodes.get(id);};
  node("arm-sim-speed").value = "2";node("arm-sim-fault").value = "grip_loss";node("arm-sim-pose-name").value = "Inspection pose";
  const drawing = [];
  node("arm-sim-canvas").getContext = () => new Proxy({}, {get(target, key) {return key in target ? target[key] : (...args) => {drawing.push([key, ...args]);};}});
  const queue = [() => response(initial)], calls = [], timers = new Map(), documentListeners = {};
  let timerId = 0, actionId = 0;
  const document = {hidden: false, getElementById: node, createElement: () => new Element(), createTextNode: (textContent) => ({textContent}), addEventListener: (name, fn) => {documentListeners[name] = fn;}};
  const crypto = {randomUUID: () => `id-${++actionId}`};
  const window = {crypto, devicePixelRatio: 1, matchMedia: () => ({matches: true}), addEventListener() {}, setTimeout(fn, delay) {const id = ++timerId;timers.set(id, {fn, delay});return id;}, clearTimeout(id) {timers.delete(id);}};
  vm.runInNewContext(source, {document, window, crypto, console, AbortController, performance: {now: () => 0}, requestAnimationFrame() {}, cancelAnimationFrame() {}, ResizeObserver: class {observe() {}}, fetch: async (url, options = {}) => {const call = {url, method: options.method || "GET", body: options.body ? JSON.parse(options.body) : null};calls.push(call);assert.ok(queue.length, "Unexpected network call");return queue.shift()(call);}});
  await flush();
  return {node, calls, queue, drawing, document, timers,
    async click(id, event = "click") {node(id).listeners[event]({preventDefault() {}});await flush();},
    playback() {return [...timers.values()].filter((item) => item.delay === 250);},
    async tick() {const entry = [...timers].find(([, timer]) => timer.delay === 250);assert.ok(entry);timers.delete(entry[0]);entry[1].fn();await flush();},
    visibility(hidden) {document.hidden = hidden;documentListeners.visibilitychange();},
    done() {assert.equal(queue.length, 0);},
  };
}
test("preset starts only from an explicit action and all six virtual joint controls exist", async () => {
  const ui = await page();assert.equal(ui.playback().length, 0);
  for (let i = 0; i < 6; i++) assert.equal(ui.node(`arm-joint-${i}`).disabled, false);
  ui.queue.push((call) => {assert.equal(call.url, "/api/simulator/arm/actions");assert.equal(call.body.action, "start");return response(snapshot("running"));});
  await ui.click("arm-sim-start");assert.equal(ui.playback().length, 1);ui.done();
});
test("manual pose sends six virtual degree values then capture and replay use independent explicit actions", async () => {
  const ui = await page();const pose = [25, 70, 120, 50, 140, 35];
  pose.forEach((value, i) => {ui.node(`arm-joint-${i}`).value = String(value);});
  ui.queue.push((call) => {assert.deepEqual(call.body.joints_deg, pose);assert.equal(call.body.action, "pose");assert.equal("pulses" in call.body, false);return response(snapshot("completed", {joints_deg: pose}));});
  await ui.click("arm-sim-pose-form", "submit");
  const recorded = [{name: "Inspection pose", joints_deg: pose, duration_s: 2}];
  ui.queue.push((call) => {assert.equal(call.body.action, "capture");assert.equal(call.body.name, "Inspection pose");return response(snapshot("completed", {joints_deg: pose, recorded_routine: recorded}));});
  await ui.click("arm-sim-record");assert.equal(ui.node("arm-sim-replay").disabled, false);
  ui.queue.push((call) => {assert.equal(call.body.action, "replay");return response(snapshot("running", {recorded_routine: recorded, routine: recorded}));});
  await ui.click("arm-sim-replay");ui.done();
});
for (const boundary of ["faulted", "completed", "stopped", "paused"]) test(`automatic virtual-arm playback halts at ${boundary}`, async () => {
  const ui = await page(snapshot("running"));ui.queue.push(() => response(snapshot(boundary)));await ui.tick();assert.equal(ui.playback().length, 0);ui.done();
});
test("fault recovery remains paused and does not dispatch automatic resume", async () => {
  const ui = await page(snapshot("faulted", {fault: "grip_loss"}));
  ui.queue.push((call) => {assert.equal(call.body.action, "clear_fault");assert.deepEqual(Object.keys(call.body).sort(), ["action", "action_id", "run_id"]);return response(snapshot("paused"));});
  await ui.click("arm-sim-clear");assert.equal(ui.playback().length, 0);assert.match(ui.node("arm-sim-start").textContent, /Resume/);ui.done();
});
test("lost mutation response recovers by reading current state without replaying the mutation", async () => {
  const ui = await page();ui.queue.push(() => {throw new Error("Response lost");});await ui.click("arm-sim-start");
  assert.equal(ui.playback().length, 0);assert.equal(ui.node("arm-sim-start").disabled, true);
  ui.queue.push((call) => {assert.equal(call.method, "GET");return response(snapshot("paused"));});await ui.click("arm-sim-reconnect");
  assert.equal(ui.calls.filter((call) => call.body?.action === "start").length, 1);ui.done();
});
test("one mutation stays in flight and hidden tabs do not advance the arm", async () => {
  const ui = await page(snapshot("running"));ui.visibility(true);assert.equal(ui.playback().length, 0);ui.visibility(false);
  let finish;ui.queue.push(() => new Promise((resolve) => {finish = resolve;}));await ui.tick();await ui.click("arm-sim-pause");
  assert.equal(ui.calls.length, 2);assert.equal(ui.playback().length, 0);finish(response(snapshot("paused")));await flush();ui.done();
});
test("fully upright virtual geometry stays inside the canvas", async () => {
  const ui = await page();const arcs = ui.drawing.filter((call) => call[0] === "arc");assert.ok(arcs.length >= 6);
  for (const [, x, y] of arcs) {assert.ok(x >= 0 && x <= 660);assert.ok(y >= 0 && y <= 330);}
  ui.done();
});

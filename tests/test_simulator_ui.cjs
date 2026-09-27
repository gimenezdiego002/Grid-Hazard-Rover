// Browser-controller recovery checks without a browser, network, or model calls.
// Run: node --test tests/test_simulator_ui.cjs
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

const web = path.join(__dirname, "..", "web");
const source = fs.readFileSync(path.join(web, "simulator.js"), "utf8");
const html = fs.readFileSync(path.join(web, "simulator.html"), "utf8");
const flush = () => new Promise(setImmediate);
const reply = (state, status = 200) => ({ok: status < 400, status, json: async () => structuredClone(state)});
const {interpolateTravel} = require("../web/simulator.js");

test("batched travel animation follows a recorded corner instead of cutting through equipment", () => {
  const obstacle = {x: 2, y: 2, width: 2, height: 2};
  const previous = {x: 1, y: 1};
  const current = {x: 5, y: 5, trail: [{x: 0, y: 1}, previous, {x: 1, y: 5}, {x: 5, y: 5}]};
  assert.deepEqual(interpolateTravel(previous, current, 0.5, [obstacle]), {x: 1, y: 5});
  assert.deepEqual(interpolateTravel(previous, current, 0.75, [obstacle]), {x: 3, y: 5});
  for (let progress = 0; progress <= 1; progress += 0.05) {
    const point = interpolateTravel(previous, current, progress, [obstacle]);
    assert.ok(point.x < 2 || point.x > 4 || point.y < 2 || point.y > 4);
  }
});

test("missing or unsafe sampled travel snaps to the authoritative endpoint", () => {
  const previous = {x: 1, y: 1}, end = {x: 5, y: 5};
  const obstacle = {x: 2, y: 2, width: 2, height: 2};
  assert.deepEqual(interpolateTravel(previous, {...end, trail: [end]}, 0.5, [obstacle]), end);
  assert.deepEqual(interpolateTravel(previous, {...end, trail: [previous, end]}, 0.5, [obstacle]), end);
  assert.deepEqual(interpolateTravel(previous, {...end, trail: [previous, {x: 1, y: 5}]}, 0.5, []), end);
});

class Element {
  constructor() {
    this.textContent = "";
    this.value = "";
    this.children = [];
    this.listeners = {};
    this.style = {};
    this.previousElementSibling = {style: {}};
    this.classList = {add() {}, remove() {}, toggle() {}};
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) {
    this.children = children;
    if (children[0]?.value && !this.value) this.value = children[0].value;
  }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  reportValidity() { return true; }
  getBoundingClientRect() { return {width: 900, height: 600, left: 0, top: 0}; }
}

function snapshot(status = "idle", extra = {}) {
  const actions = {
    idle: ["start", "direct", "reset"], running: ["step", "pause", "stop", "inject_fault", "reset"],
    paused: ["step", "resume", "stop", "inject_fault", "reset"],
    faulted: ["clear_fault", "stop", "reset"], needs_review: ["review", "stop", "reset"],
    completed: ["reset"], stopped: ["reset"],
  };
  return {
    run_id: "test-run-1", status, stage: status === "needs_review" ? "human_review" : "rover_patrol",
    simulated: true, mode: "preset", elapsed_s: 0, actual_api_cost_usd: 0,
    world: {width_m: 24, height_m: 16, obstacles: [], station: {x: 3, y: 12},
            hazard: {x: 20, y: 11, radius_m: 1.5}, patrol: []},
    robots: ["rover", "hexapod"].map((id, i) => ({id, name: id, kind: i ? "hexapod" : "wheeled",
      x: 2, y: 2 + i * 3, path: [], trail: [], heading_deg: 0, speed_mps: 1,
      state: "idle", distance_m: 0, battery_pct: 100, sensors: {valid: true, hazard_signal: 0, nearest_obstacle_m: 2}})),
    events: [], metrics: {modeled_request_allowance: 6}, review: {required: status === "needs_review"},
    arm_handoff: {status: "awaiting_inspection", proposal: null}, allowed_actions: actions[status], ...extra,
  };
}

async function page(initial = snapshot()) {
  const nodes = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map((match) => [match[1], new Element()]));
  const node = (id) => { assert.ok(nodes.has(id), `Unknown page element ${id}`); return nodes.get(id); };
  node("scenario").value = "preset";
  node("speed").value = "2";
  node("fault").value = "sensor_dropout";
  node("facility-map").getContext = () => new Proxy({}, {
    get(target, prop) {
      if (prop === "createRadialGradient") return () => ({addColorStop() {}});
      return prop in target ? target[prop] : () => {};
    },
  });
  const queue = [() => reply(initial)], calls = [], unexpected = [], timers = new Map();
  const documentListeners = {}, windowListeners = {};
  let timerSequence = 0, actionSequence = 0;
  const document = {hidden: false, getElementById: node,
    createElement: () => new Element(), createTextNode: (textContent) => ({textContent}),
    addEventListener: (name, fn) => { documentListeners[name] = fn; }};
  const crypto = {randomUUID: () => `uuid-${++actionSequence}`};
  const window = {crypto, devicePixelRatio: 1, matchMedia: () => ({matches: true}),
    setTimeout: (fn, delay) => { const id = ++timerSequence; timers.set(id, {fn, delay}); return id; },
    clearTimeout: (id) => timers.delete(id), addEventListener: (name, fn) => { windowListeners[name] = fn; }};
  const context = {console, document, window, crypto, AbortController, performance: {now: () => 0},
    requestAnimationFrame: () => 0, cancelAnimationFrame() {}, ResizeObserver: class {observe() {}},
    fetch: async (url, options = {}) => {
      const call = {url, method: options.method || "GET", body: options.body ? JSON.parse(options.body) : null};
      calls.push(call);
      const next = queue.shift();
      if (!next) { unexpected.push(call); throw new Error(`Unexpected request ${url}`); }
      return next(call);
    }};
  vm.runInNewContext(source, context, {filename: "web/simulator.js"});
  await flush();
  return {
    node, queue, calls, document,
    async click(id, event = "click") { node(id).listeners[event]({preventDefault() {}}); await flush(); },
    playbackTimers() { return [...timers.values()].filter((timer) => timer.delay === 500); },
    async tick() {
      const entry = [...timers.entries()].find(([, timer]) => timer.delay === 500);
      assert.ok(entry, "Expected one scheduled playback tick");
      timers.delete(entry[0]); entry[1].fn(); await flush();
    },
    visibility(hidden) { document.hidden = hidden; documentListeners.visibilitychange(); },
    done() { assert.equal(queue.length, 0, "All expected network requests occurred"); assert.deepEqual(unexpected, []); },
  };
}

test("directed inspection sends the supported target-only command", async () => {
  const ui = await page();
  ui.node("scenario").value = "directed";
  ui.node("target-robot").value = "hexapod"; // This selector affects faults, not mission ownership.
  ui.node("target-x").value = "5";
  ui.node("target-y").value = "4";
  ui.queue.push((call) => {
    assert.equal(call.body.action, "direct");
    assert.deepEqual(call.body.target, {x: 5, y: 4});
    assert.equal("robot_id" in call.body, false);
    return reply(snapshot("running", {mode: "directed"}));
  });
  await ui.click("start");
  assert.equal(ui.playbackTimers().length, 1);
  ui.done();
});

test("directed form follows the returned mission mode and idle reset preserves the chosen mode", async () => {
  const ui = await page();
  assert.equal(ui.node("scenario").value, "preset");
  ui.node("target-x").value = "5";
  ui.node("target-y").value = "4";
  ui.queue.push((call) => {
    assert.equal(call.body.action, "direct");
    return reply(snapshot("running", {mode: "directed", stage: "rover_investigate"}));
  });
  await ui.click("target-form", "submit");
  assert.equal(ui.node("scenario").value, "directed");
  assert.match(ui.node("scenario-description").textContent, /rover leads/i);
  assert.doesNotMatch(ui.node("scenario-description").textContent, /patrol/i);
  ui.queue.push(() => reply(snapshot("idle", {run_id: "test-run-2", mode: "preset"})));
  await ui.click("reset");
  assert.equal(ui.node("scenario").value, "directed");
  assert.equal(ui.node("scenario").disabled, false);
  ui.done();
});

test("clear fault omits unsupported fields and does not resume automatically", async () => {
  const ui = await page(snapshot("faulted"));
  ui.queue.push((call) => {
    assert.deepEqual(Object.keys(call.body).sort(), ["action", "action_id", "run_id"]);
    assert.equal(call.body.action, "clear_fault");
    return reply(snapshot("paused"));
  });
  await ui.click("clear-fault");
  assert.equal(ui.playbackTimers().length, 0);
  assert.equal(ui.node("step").disabled, false);
  assert.match(ui.node("start").textContent, /Resume/);
  ui.done();
});

test("reloading a directed mission displays the server target and replaces stale local coordinates", async () => {
  const directed = {mode: "directed", target: {x: 19, y: 10}};
  const ui = await page(snapshot("paused", directed));
  assert.equal(ui.node("scenario").value, "directed");
  assert.equal(Number(ui.node("target-x").value), 19);
  assert.equal(Number(ui.node("target-y").value), 10);
  assert.equal(ui.node("target-x").disabled, true);
  ui.node("target-x").value = "9";
  ui.node("target-y").value = "8";
  ui.queue.push(() => reply(snapshot("paused", {...directed, elapsed_s: 1})));
  await ui.click("step");
  assert.equal(Number(ui.node("target-x").value), 19);
  assert.equal(Number(ui.node("target-y").value), 10);
  ui.done();
});

test("lost mutation response stops playback and recovers with a read, never a duplicate mutation", async () => {
  const ui = await page();
  ui.queue.push(() => { throw new TypeError("Lost response after server accepted start"); });
  await ui.click("start");
  assert.equal(ui.node("start").disabled, true);
  assert.equal(ui.playbackTimers().length, 0);
  await ui.click("start");
  assert.equal(ui.calls.length, 2);
  ui.queue.push((call) => { assert.equal(call.method, "GET"); return reply(snapshot("running", {elapsed_s: 4})); });
  await ui.click("reconnect");
  assert.equal(ui.calls.filter((call) => call.body?.action === "start").length, 1);
  assert.equal(ui.node("pause").disabled, false);
  ui.done();
});

test("only one mutation is in flight, even when a user clicks during a slow playback tick", async () => {
  const ui = await page(snapshot("running"));
  let finish;
  ui.queue.push(() => new Promise((resolve) => { finish = resolve; }));
  await ui.tick();
  assert.equal(ui.playbackTimers().length, 0);
  assert.equal(ui.node("pause").disabled, true);
  await ui.click("pause");
  assert.equal(ui.calls.length, 2);
  finish(reply(snapshot("running", {elapsed_s: 1})));
  await flush();
  assert.equal(ui.playbackTimers().length, 1);
  ui.done();
});

for (const boundary of ["needs_review", "faulted", "completed", "stopped"]) {
  test(`autoplay stops at the server's ${boundary} boundary`, async () => {
    const ui = await page(snapshot("running"));
    ui.queue.push(() => reply(snapshot(boundary, {elapsed_s: 60})));
    await ui.tick();
    assert.equal(ui.playbackTimers().length, 0);
    assert.equal(ui.node("step").disabled, true);
    ui.done();
  });
}

test("reconnecting after a lost reset uses the new run ID for all later commands", async () => {
  const ui = await page(snapshot("completed"));
  ui.queue.push(() => { throw new TypeError("Lost reset response"); });
  await ui.click("reset");
  assert.equal(ui.node("reset").disabled, true);
  ui.queue.push(() => reply(snapshot("idle", {run_id: "test-run-2"})));
  await ui.click("reconnect");
  ui.queue.push((call) => {
    assert.equal(call.body.run_id, "test-run-2");
    assert.equal(call.body.action, "start");
    return reply(snapshot("running", {run_id: "test-run-2"}));
  });
  await ui.click("start");
  assert.equal(ui.calls.filter((call) => call.body?.action === "reset").length, 1);
  ui.done();
});

test("hidden tabs stop scheduled work and speed controls produce bounded steps", async () => {
  const ui = await page(snapshot("running"));
  ui.node("speed").value = "8";
  await ui.click("speed", "change");
  ui.visibility(true);
  assert.equal(ui.playbackTimers().length, 0);
  ui.visibility(false);
  assert.equal(ui.playbackTimers().length, 1);
  ui.queue.push((call) => {
    assert.equal(call.body.dt_s, 0.5);
    assert.equal(call.body.steps, 8);
    return reply(snapshot("running", {elapsed_s: 4}));
  });
  await ui.tick();
  ui.done();
});

test("the visible stop control terminates playback without resetting evidence", async () => {
  const ui = await page(snapshot("running"));
  assert.equal(ui.node("stop").disabled, false);
  ui.queue.push((call) => {
    assert.equal(call.body.action, "stop");
    return reply(snapshot("stopped", {elapsed_s: 17, metrics: {observations: 12}}));
  });
  await ui.click("stop");
  assert.equal(ui.playbackTimers().length, 0);
  assert.equal(ui.node("stop").disabled, true);
  assert.match(ui.node("metric-clock").textContent, /00:17/);
  assert.match(ui.node("economy-summary").textContent, /12 observations/);
  ui.done();
});

test("an obstructed directed target can be corrected without reconnecting or losing the scene", async () => {
  const ui = await page();
  ui.node("scenario").value = "directed";
  ui.node("target-x").value = "9";
  ui.node("target-y").value = "8";
  ui.queue.push(() => reply({detail: "Target must be a free point inside the local world"}, 400));
  await ui.click("start");
  assert.equal(ui.node("start").disabled, false);
  assert.equal(ui.node("error-banner").hidden, false);
  assert.match(ui.node("control-status").textContent, /Request rejected/);
  ui.node("target-x").value = "5";
  ui.node("target-y").value = "4";
  ui.queue.push((call) => {
    assert.deepEqual(call.body.target, {x: 5, y: 4});
    return reply(snapshot("running"));
  });
  await ui.click("start");
  assert.equal(ui.calls.filter((call) => call.method === "GET").length, 1);
  assert.equal(ui.node("error-banner").hidden, true);
  ui.done();
});

test("human review shows the concrete arm preview and cannot bypass budget refusal", async () => {
  const ui = await page(snapshot("needs_review", {
    metrics: {modeled_request_allowance: 0, budget_refused: true},
    arm_handoff: {status: "needs_review", proposal: {action: "place_marker", target_id: "learm",
      preview_only: true, inspection: {station_id: "station-a", evidence_ref: "sim://test/inspection"}}},
  }));
  assert.equal(ui.node("review").disabled, true);
  assert.equal(ui.node("arm-queue").children.length, 1);
  const text = (element) => [element.textContent || "", ...(element.children || []).map(text)].join(" ");
  assert.match(text(ui.node("arm-queue")), /place marker/i);
  assert.match(text(ui.node("arm-queue")), /station-a/i);
  assert.equal(ui.playbackTimers().length, 0);
  ui.done();
});

// Offline browser-controller checks. Run: node --test tests/test_dashboard_recovery.cjs
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

const web = path.join(__dirname, "..", "web");
const source = fs.readFileSync(path.join(web, "app.js"), "utf8");
const html = fs.readFileSync(path.join(web, "index.html"), "utf8");

class Element {
  constructor() {
    this.textContent = "";
    this.value = "";
    this.checked = false;
    this.listeners = {};
    this.children = [];
    this.classList = {toggle() {}};
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  setAttribute() {}
  reportValidity() { return true; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
}

const reply = (body, status = 200) => ({ok: status < 400, status, json: async () => structuredClone(body)});
const disconnected = () => { throw new TypeError("Connection interrupted"); };

function mission(id, events, status = "planned", next = null) {
  return {
    mission_id: id, mode: "preset", station_id: "station-a", target_id: "inspection-area",
    status, progress: {completed: 0, total: 4}, proposed_tasks: [], blockers: [],
    allowed_actions: status === "planned" ? ["start", "cancel"] : status === "needs_review" ? ["simulate_review", "cancel"] : ["complete_task", "pause", "cancel"],
    next_task: next ? {task_id: next} : null,
    events: events.map((action_id) => ({action_id}))
  };
}

async function dashboard() {
  const nodes = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map((match) => [match[1], new Element()]));
  const node = (id) => { assert.ok(nodes.has(id), "Unknown page element: " + id); return nodes.get(id); };
  node("mission-mode").value = "preset";
  node("mission-station").value = "station-a";
  node("mission-target").value = "inspection-area";
  const steps = [];
  const calls = [];
  const unexpected = [];
  let sequence = 0;
  const context = {
    console, Error, TypeError, structuredClone,
    crypto: {randomUUID: () => "id-" + ++sequence},
    document: {getElementById: node, createElement: () => new Element(), createElementNS: () => new Element()},
    fetch: async (url, options = {}) => {
      if (url === "/health") return reply({status: "ok"});
      if (url === "/scenarios/leak.json") return reply({observations: [], budget: {max_requests: 12, max_tokens: 24000, max_usd: "0.10"}});
      if (url === "/api/missions/inventory") return reply({inventory: []});
      const call = {url, method: options.method || "GET", body: options.body ? JSON.parse(options.body) : null};
      calls.push(call);
      const step = steps.shift();
      if (!step) { unexpected.push(call); throw new Error("Unexpected request: " + url); }
      return step(call);
    }
  };
  vm.runInNewContext(source, context, {filename: "web/app.js"});
  await new Promise(setImmediate);
  assert.equal(node("create-mission").disabled, false);
  return {
    node, calls, steps,
    async click(id, event = "click") { await node(id).listeners[event]({preventDefault() {}}); },
    done() { assert.equal(steps.length, 0, "Every expected request must occur"); assert.deepEqual(unexpected, []); },
    async create(status = "planned", next = null) {
      let state;
      steps.push((call) => { state = mission(call.body.mission_id, [call.body.action_id], status, next); return reply(state); });
      await this.click("mission-plan-form", "submit");
      return state;
    }
  };
}

test("lost creation response recovers the existing mission without another POST", async () => {
  const page = await dashboard();
  let saved;
  page.steps.push((call) => { saved = mission(call.body.mission_id, [call.body.action_id]); return disconnected(); });
  page.steps.push((call) => { assert.equal(call.url, "/api/missions/" + saved.mission_id); return reply(saved); });
  await page.click("mission-plan-form", "submit");
  assert.match(page.node("mission-plan-status").textContent, /Recovered the saved mission/);
  assert.equal(page.node("mission-retry").hidden, true);
  assert.equal(page.node("mission-start").disabled, false);
  assert.equal(page.calls.filter((call) => call.method === "POST").length, 1);
  page.done();
});

test("uncertain creation keeps the exact ID and original form values for explicit retry", async () => {
  const page = await dashboard();
  page.steps.push(disconnected, () => reply({detail: "Mission not found"}, 404));
  await page.click("mission-plan-form", "submit");
  const first = page.calls[0];
  assert.equal(page.node("mission-retry").hidden, false);
  assert.equal(page.node("create-mission").disabled, true);
  page.node("mission-target").value = "changed-after-request";
  await page.click("mission-plan-form", "submit");
  assert.equal(page.calls.length, 2, "A second creation must stay blocked");
  page.steps.push((call) => { assert.deepEqual(call, first); return reply(mission(call.body.mission_id, [call.body.action_id])); });
  await page.click("mission-retry");
  assert.equal(page.node("mission-retry").hidden, true);
  assert.equal(page.node("create-mission").disabled, false);
  page.done();
});

test("lost start response reloads the recorded action and the next task", async () => {
  const page = await dashboard();
  const prior = await page.create();
  let saved;
  page.steps.push((call) => { saved = mission(prior.mission_id, [...prior.events.map((event) => event.action_id), call.body.action_id], "running", "monitor"); return disconnected(); });
  page.steps.push(() => reply(saved));
  await page.click("mission-start");
  assert.equal(page.node("mission-start").hidden, true);
  assert.equal(page.node("mission-advance").disabled, false);
  assert.equal(JSON.parse(page.node("mission-record").textContent).next_task.task_id, "monitor");
  assert.equal(page.calls.filter((call) => call.body?.action === "start").length, 1);
  page.done();
});

test("unknown task outcome blocks other actions and retries the original task", async () => {
  const page = await dashboard();
  const prior = await page.create("running", "monitor");
  page.steps.push(disconnected, () => reply(prior));
  await page.click("mission-advance");
  const first = page.calls[1];
  assert.equal(page.node("mission-advance").disabled, true);
  assert.equal(page.node("mission-cancel").disabled, true);
  await page.click("mission-advance");
  assert.equal(page.calls.length, 3);
  page.steps.push((call) => { assert.deepEqual(call, first); return reply(mission(prior.mission_id, [call.body.action_id], "running", "scout")); });
  await page.click("mission-retry");
  assert.equal(JSON.parse(page.node("mission-record").textContent).next_task.task_id, "scout");
  assert.equal(page.node("mission-advance").disabled, false);
  page.done();
});

test("retrying a scout completion preserves the analysis result without rerunning analysis", async () => {
  const page = await dashboard();
  const prior = await page.create("running", "scout");
  page.steps.push((call) => { assert.equal(call.url, "/api/run"); return reply({strategy: "economy", outcome: "complete", events: [], findings: [{status: "suspected_hazard"}], accounting: {actual_paid_usd: 0}}); });
  page.steps.push(disconnected, disconnected);
  await page.click("mission-advance");
  const originalCompletion = page.calls[2];
  page.steps.push((call) => { assert.deepEqual(call, originalCompletion); return reply(mission(prior.mission_id, [call.body.action_id], "needs_review")); });
  await page.click("mission-retry");
  assert.equal(page.calls.filter((call) => call.url === "/api/run").length, 1);
  assert.equal(originalCompletion.body.payload.outcome, "suspected_hazard");
  assert.equal(page.node("mission-review").hidden, false);
  page.done();
});

test("a state conflict refreshes the mission instead of stranding stale controls", async () => {
  const page = await dashboard();
  const prior = await page.create("running", "scout");
  page.steps.push(() => reply({detail: "Action conflicts"}, 409), () => reply(mission(prior.mission_id, ["other-action"], "needs_review")));
  await page.click("mission-pause");
  assert.equal(page.node("mission-advance").hidden, true);
  assert.equal(page.node("mission-review").disabled, false);
  assert.equal(page.node("mission-retry").hidden, true);
  assert.match(page.node("mission-plan-status").textContent, /Current mission state was reloaded/);
  page.done();
});

test("service restart keeps the last record but disables its commands", async () => {
  const page = await dashboard();
  await page.create();
  const oldRecord = page.node("mission-record").textContent;
  page.steps.push(() => reply({detail: "Mission not found"}, 404), () => reply({detail: "Mission not found"}, 404));
  await page.click("mission-start");
  assert.equal(page.node("mission-record").textContent, oldRecord);
  assert.equal(page.node("mission-start").disabled, true);
  assert.equal(page.node("create-mission").disabled, false);
  assert.equal(page.node("mission-retry").hidden, true);
  assert.match(page.node("mission-plan-status").textContent, /last record is retained/);
  page.done();
});

test("a conflict with an unavailable read keeps controls paused until reconciliation", async () => {
  const page = await dashboard();
  const prior = await page.create();
  page.steps.push(() => reply({detail: "Action conflicts"}, 409), disconnected);
  await page.click("mission-start");
  const first = page.calls[1];
  assert.equal(page.node("mission-retry").hidden, false);
  assert.equal(page.node("mission-start").disabled, true);
  page.steps.push((call) => { assert.deepEqual(call, first); return reply({detail: "Action conflicts"}, 409); });
  page.steps.push(() => reply(mission(prior.mission_id, ["another-start"], "running", "monitor")));
  await page.click("mission-retry");
  assert.equal(page.node("mission-retry").hidden, true);
  assert.equal(page.node("mission-advance").disabled, false);
  page.done();
});

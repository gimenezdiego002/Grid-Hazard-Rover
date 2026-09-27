// Real React effects and DOM behavior, with an offline clock and no browser/network.
// Dependencies live in deploy/vercel-simulator; no project-root node_modules needed.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {createHash} = require("node:crypto");
const {createRequire} = require("node:module");
const {beforeEach, afterEach, test} = require("node:test");

const repository = path.resolve(__dirname, "..");
const deployment = path.join(repository, "deploy/vercel-simulator");
const dependencies = createRequire(path.join(deployment, "package.json"));
const {JSDOM} = dependencies("jsdom");
const {buildSync} = dependencies("esbuild");
const directory = path.join(repository, "web/team-simulator");
const fixtures = JSON.parse(fs.readFileSync(path.join(directory, "fixtures.json"), "utf8"));
const dom = new JSDOM('<!doctype html><html><body><div id="test-root"></div></body></html>', {
  url: "https://offline-simulator.test/",
});
global.window = dom.window;
global.document = dom.window.document;
global.HTMLElement = dom.window.HTMLElement;
Object.defineProperty(global, "navigator", {value: dom.window.navigator, configurable: true});
global.IS_REACT_ACT_ENVIRONMENT = true;
const React = dependencies("react");
const {createRoot} = dependencies("react-dom/client");

// Compile the real component, without writing a generated bundle or executing main.tsx.
const compiled = buildSync({
  entryPoints: [path.join(directory, "RoverDemo.tsx")],
  bundle: true, write: false, platform: "node", format: "cjs", jsx: "automatic",
  external: ["react", "react-dom", "react/jsx-runtime"],
  nodePaths: [path.join(deployment, "node_modules")],
});
const componentModule = {exports: {}};
new Function("require", "module", "exports", "performance", compiled.outputFiles[0].text)(
  dependencies, componentModule, componentModule.exports, window.performance,
);
const RoverDemo = componentModule.exports.default;

let root, now, intervalId, intervals, attemptedConnections;
const host = document.getElementById("test-root");
const query = (selector) => host.querySelector(selector);
const text = (selector) => query(selector)?.textContent;
const cards = () => [...host.querySelectorAll(".inspection-card")];
const points = () => [...host.querySelectorAll(".inspection-point")];
const failConnection = () => {attemptedConnections += 1;throw new Error("The teammate rehearsal attempted a connection");};

// JSDOM has no native top layer. Model only showModal/close; the component's
// own cancel handler, state cleanup, and opener-focus restoration remain real.
dom.window.HTMLDialogElement.prototype.showModal = function () {
  this.setAttribute("open", "");
  this.querySelector("[autofocus], button")?.focus();
};
dom.window.HTMLDialogElement.prototype.close = function () {
  this.removeAttribute("open");
};

beforeEach(() => {
  now = 0;intervalId = 0;intervals = new Map();attemptedConnections = 0;
  Object.defineProperty(window.performance, "now", {value: () => now, configurable: true});
  window.setInterval = (callback, period) => {
    assert.ok(Number.isFinite(period) && period > 0);
    const id = ++intervalId;intervals.set(id, {callback, period, next: now + period});return id;
  };
  window.clearInterval = (id) => intervals.delete(id);
  window.fetch = global.fetch = failConnection;
  window.WebSocket = window.XMLHttpRequest = class {constructor() {failConnection();}};
  Object.defineProperty(window.navigator, "bluetooth", {value: {requestDevice: failConnection}, configurable: true});
  root = createRoot(host);
});

afterEach(async () => {
  await React.act(async () => root.unmount());
  assert.equal(intervals.size, 0, "Unmount must cancel playback");
  assert.equal(attemptedConnections, 0, "Rendering and playback remain offline");
  host.replaceChildren();
});

async function render(hazards = fixtures) {
  await React.act(async () => root.render(React.createElement(React.StrictMode, null,
    React.createElement(RoverDemo, {hazards}))));
}

async function click(element) {
  assert.ok(element, "Expected an interactive element");
  await React.act(async () => element.click());
}

async function advance(milliseconds) {
  const end = now + milliseconds;
  await React.act(async () => {
    let guard = 0;
    while (true) {
      const next = [...intervals.entries()].filter(([, entry]) => entry.next <= end)
        .sort((a, b) => a[1].next - b[1].next)[0];
      if (!next) break;
      assert.ok(++guard < 1000, "Playback timers must be finite");
      now = next[1].next;next[1].next += next[1].period;next[1].callback();
    }
    now = end;
  });
}

test("the initial view labels simulation and withholds evidence until replay reaches it", async () => {
  await render();
  assert.match(host.textContent, /simulat/i);
  assert.match(host.textContent, /physical actuation.*disabled/i);
  assert.equal(text(".street-reset").trim(), "Reset street");
  assert.match(text("#street-reset-help"), /Fleet and arm simulations keep their state/);
  assert.deepEqual([...host.querySelectorAll(".street-technologies span")].map((badge) => badge.textContent), ["React", "TypeScript", "SVG"]);
  assert.equal(text(".mission-progress strong"), "0%");
  assert.equal(cards().length, 0);
  assert.ok(points().every((button) => button.disabled));
  assert.equal(intervals.size, 0);
  await advance(10000);
  assert.equal(text(".mission-status strong"), "Mission ready");
  assert.equal(cards().length, 0);
});

test("playback reveals each fixture at its stage and stops on the final stage", async () => {
  await render();await click(query(".mission-controls .primary"));
  assert.equal(intervals.size, 1, "StrictMode must not duplicate the playback clock");
  await advance(1800);
  assert.equal(text(".mission-progress strong"), "25%");
  assert.equal(cards().length, 0);
  await advance(1800);
  assert.match(text(".mission-status strong"), /replaying fixture evidence/i);
  assert.equal(cards().length, 1);
  assert.equal(points()[0].disabled, false);
  assert.ok(points().slice(1).every((button) => button.disabled));
  await advance(1800);
  assert.equal(cards().length, Math.min(2, fixtures.length));
  await advance(1800);
  assert.equal(text(".mission-progress strong"), "100%");
  assert.match(text(".mission-status strong"), /report preview ready/i);
  assert.equal(cards().length, fixtures.length);
  assert.equal(query(".mission-controls .primary").disabled, true);
  assert.match(text(".mission-controls .primary"), /Completed/);
  assert.equal(query(".hexapod").classList.contains("walking"), false);
  assert.equal(intervals.size, 0);
  const completedTime = text(".rover-telemetry strong");
  await advance(10000);
  assert.equal(text(".rover-telemetry strong"), completedTime);
});

test("pause freezes progress and resume preserves partial-stage elapsed time", async () => {
  await render();await click(query(".mission-controls .primary"));
  await advance(1050);await click(query(".mission-controls .primary"));
  const pausedTime = text(".rover-telemetry strong");
  assert.equal(intervals.size, 0);
  await advance(5000);
  assert.equal(text(".rover-telemetry strong"), pausedTime);
  assert.equal(text(".mission-progress strong"), "0%");
  await click(query(".mission-controls .primary"));await advance(750);
  // Flush the final fraction of a timer period through the actual Pause action.
  await click(query(".mission-controls .primary"));
  assert.equal(text(".mission-progress strong"), "25%");
  assert.equal(cards().length, 0);
});

test("reset clears elapsed time, captured fixtures, and a running playback", async () => {
  await render();await click(query(".mission-controls .primary"));await advance(5400);
  assert.ok(cards().length > 0);
  await click(query(".mission-controls .secondary"));
  assert.equal(text(".mission-status strong"), "Mission ready");
  assert.equal(text(".mission-progress strong"), "0%");
  assert.equal(text(".rover-telemetry strong"), "T+00:00");
  assert.equal(cards().length, 0);
  assert.ok(points().every((button) => button.disabled));
  assert.equal(intervals.size, 0);
  await advance(10000);
  assert.equal(text(".mission-progress strong"), "0%");
});

test("street reset closes evidence and starts a fresh single-clock replay", async () => {
  await render();await click(query(".mission-controls .primary"));await advance(3600);
  await click(query(".inspection-preview"));
  assert.ok(query("dialog[open]"));
  // Native dialogs make the background inert; exercise the reset handler here
  // to verify its cleanup even if another page control requests a street reset.
  await click(query(".street-reset"));
  assert.equal(query("dialog"), null);
  assert.equal(cards().length, 0);
  assert.equal(intervals.size, 0);
  await click(query(".mission-controls .primary"));
  assert.equal(intervals.size, 1);
  await advance(1800);
  assert.equal(text(".mission-progress strong"), "25%");
  assert.equal(text(".rover-telemetry strong"), "T+00:01");
  assert.equal(cards().length, 0);
  await advance(5400);
  assert.equal(text(".mission-progress strong"), "100%");
  assert.equal(intervals.size, 0);
});

test("modal close and keyboard-cancel paths restore focus to the evidence opener", async () => {
  await render();await click(query(".mission-controls .primary"));await advance(3600);
  const opener = query(".inspection-preview");
  opener.focus();await click(opener);
  let dialog = query("dialog[open]");
  assert.ok(dialog, "Evidence must use the native modal dialog");
  const close = dialog.querySelector('[aria-label="Close evidence"]');
  assert.equal(document.activeElement, close);
  await click(close);
  assert.equal(query("dialog[open]"), null);
  assert.equal(document.activeElement, opener);
  await click(opener);dialog = query("dialog[open]");
  // Browsers dispatch cancel for Escape; native Escape/top-layer behavior is
  // checked in the real-browser rehearsal, not imitated as a React handler.
  await React.act(async () => dialog.dispatchEvent(new window.Event("cancel", {cancelable: true})));
  assert.equal(query("dialog[open]"), null);
  assert.equal(document.activeElement, opener);
});

test("dialog backdrop closes without treating an inner click as dismissal", async () => {
  await render();await click(query(".mission-controls .primary"));await advance(3600);
  const opener = points()[0];opener.focus();await click(opener);
  const dialog = query("dialog[open]");assert.ok(dialog);
  await click(dialog.querySelector("article"));assert.ok(query("dialog[open]"));
  await click(dialog);assert.equal(query("dialog[open]"), null);
  assert.equal(document.activeElement, opener);
});

test("the public fixture and source boundary cannot silently acquire live evidence or transport", () => {
  const provenance = JSON.parse(fs.readFileSync(path.join(directory, "provenance.json"), "utf8"));
  assert.equal(provenance.simulated, true);
  assert.equal(provenance.physical_connected, false);
  assert.equal(provenance.actuation_enabled, false);
  assert.equal(provenance.model_calls, 0);
  assert.equal(provenance.backend_submissions, 0);
  for (const [name, record] of Object.entries(provenance.local_files)) {
    assert.equal(createHash("sha256").update(fs.readFileSync(path.join(directory, name))).digest("hex"), record.sha256,
      `Provenance must describe the actual adapted ${name}`);
  }
  assert.ok(fixtures.length > 0 && fixtures.length <= 3);
  for (const fixture of fixtures) {
    assert.equal(fixture.image_url, null, "This static rehearsal retains no uploaded camera image");
    assert.ok(fixture.metadata?.simulated === true || fixture.metadata?.demo === true);
    assert.equal(fixture.location.type, "Point");
    assert.equal(fixture.location.coordinates.length, 2);
  }
  for (const name of fs.readdirSync(directory).filter((name) => /\.(?:ts|tsx|json)$/.test(name))) {
    const content = fs.readFileSync(path.join(directory, name), "utf8");
    assert.doesNotMatch(content, /\bfetch\s*\(|\bXMLHttpRequest\b|\bWebSocket\b|navigator\.(?:bluetooth|serial)|import\s+[\s\S]*?from\s*["'](?:bleak|serial|https?|net)["']/);
    assert.doesNotMatch(content, /(?:AIza[\w-]{25,}|ghp_[\w]{25,}|-----BEGIN .*PRIVATE KEY-----|https?:\/\/[^\s"']*ngrok|(?:[\da-f]{2}:){5}[\da-f]{2})/i);
  }
});

/* Integration proof in real Pyodide/WASM, using the exact Python source files. */
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {fileURLToPath} from "node:url";
import {loadPyodide} from "pyodide";
import {initializeSimulator} from "./worker.mjs";

const sourceRoot = new URL("../../src/relay_gateway/", import.meta.url);
const runtime = await initializeSimulator(loadPyodide, (name) => readFile(new URL(name, sourceRoot), "utf8"));
assert.equal(runtime.version, "314.0.7");
let sequence = 0;
const read = (path) => {
  const result = runtime.dispatch({path, method: "GET", body: null});
  assert.equal(result.status, 200);
  return result.body;
};
const apply = (path, action, params = {}, id = `node-${++sequence}`) => {
  const before = read(path);
  return runtime.dispatch({path: `${path}/actions`, method: "POST",
    body: {run_id: before.run_id, action_id: id, action, ...params}});
};
const run = (path, action, params) => {
  const result = apply(path, action, params);
  assert.equal(result.status, 200, JSON.stringify(result));
  return result.body;
};
const finish = (path) => {
  let state = read(path);
  for (let i = 0; state.status === "running" && i < 200; i++) {
    state = run(path, "step", {dt_s: 0.5, steps: 20});
  }
  assert.notEqual(state.status, "running", "A finite routine must reach its next boundary");
  return state;
};

const fleetPath = "/api/simulator", armPath = "/api/simulator/arm";
const initialFleet = read(fleetPath), initialArm = read(armPath);
assert.match(initialFleet.run_id, /^sim-[a-f0-9]+-1$/); // Real uuid4 and RLock succeeded in WASM.
assert.match(initialArm.run_id, /^arm-sim-[a-f0-9]+-1$/);
assert.equal(initialFleet.storage, "browser_tab_memory");
assert.equal(initialArm.session_scope, "this_browser_tab_until_reload");

run(fleetPath, "start");
const review = finish(fleetPath);
assert.equal(review.status, "needs_review");
assert.equal(review.stage, "human_review");
assert.equal(review.elapsed_s, 56.5);
assert.equal(review.arm_handoff.proposal.preview_only, true); // Relative handoff import + SHA256 works.
assert.equal(apply(fleetPath, "step").status, 409);
run(fleetPath, "review", {decision: "acknowledge"});
const fleetDone = finish(fleetPath);
assert.equal(fleetDone.status, "completed");
assert.equal(fleetDone.elapsed_s, 78);
assert.equal(fleetDone.metrics.baseline_requests, 80);
assert.equal(fleetDone.metrics.governed_requests, 3);
assert.equal(fleetDone.metrics.actual_model_calls, 0);
assert.equal(fleetDone.metrics.actual_api_cost_usd, 0);
assert.deepEqual(read(armPath), initialArm, "Fleet requests cannot advance the independent arm");

run(armPath, "start");
const armDone = finish(armPath);
assert.equal(armDone.status, "completed");
assert.equal(armDone.elapsed_s, 14);
assert.equal(armDone.payload.state, "placed");
assert.equal(armDone.commands_dispatched, 0);
assert.equal(armDone.physical_result, null);

run(armPath, "reset");
run(armPath, "capture", {name: "home", duration_s: 1});
run(armPath, "pose", {joints_deg: [100, 70, 90, 80, 100, 30], duration_s: 1});
finish(armPath);
run(armPath, "capture", {name: "view", duration_s: 1});
run(armPath, "replay", {repeats: 2});
const taught = finish(armPath);
assert.equal(taught.status, "completed");
assert.equal(taught.repeat_index, 2);
assert.equal(taught.recorded_routine.length, 2);
assert.equal(taught.recording.recording_kind, "simulated_joint_angles");
assert.equal(taught.recording.angle_unit, "degrees");

run(armPath, "reset");
run(armPath, "start");
const held = run(armPath, "step", {dt_s: 1, steps: 4});
assert.equal(held.payload.state, "held");
const faulted = run(armPath, "inject_fault", {fault: "grip_loss"});
assert.equal(faulted.payload.state, "dropped");
assert.equal(apply(armPath, "resume").status, 409);
assert.equal(apply(armPath, "step").status, 409);
assert.deepEqual(read(armPath), faulted);
const recovered = run(armPath, "clear_fault");
assert.equal(recovered.status, "paused");
assert.equal(recovered.payload.state, "held");
run(armPath, "resume");
assert.equal(finish(armPath).payload.state, "placed");

run(fleetPath, "reset");
run(fleetPath, "start");
run(fleetPath, "inject_fault", {robot_id: "rover", fault: "budget_exhausted"});
const refused = finish(fleetPath);
assert.equal(refused.status, "needs_review");
assert.equal(refused.metrics.budget_refused, true);
assert.equal(apply(fleetPath, "review", {decision: "acknowledge"}).status, 409);

run(fleetPath, "reset");
run(fleetPath, "direct", {target: {x: 5, y: 4}});
const first = apply(fleetPath, "step", {dt_s: 0.5}, "same-step");
const retried = apply(fleetPath, "step", {dt_s: 0.5}, "same-step");
assert.equal(retried.body.replayed, true);
assert.equal(retried.body.elapsed_s, first.body.elapsed_s);
assert.equal(apply(fleetPath, "step", {dt_s: 1}, "same-step").status, 409);
run(fleetPath, "pause");
const paused = run(fleetPath, "step", {dt_s: 0.5});
assert.equal(paused.status, "paused");
run(fleetPath, "inject_fault", {robot_id: "rover", fault: "sensor_dropout"});
assert.equal(run(fleetPath, "clear_fault").status, "paused");
run(fleetPath, "resume");
assert.equal(finish(fleetPath).stage, "human_review");

const stale = read(fleetPath).run_id;
run(fleetPath, "reset");
assert.equal(runtime.dispatch({path: `${fleetPath}/actions`, method: "POST",
  body: {run_id: stale, action_id: "stale-request", action: "start"}}).status, 409);
const beforeBad = read(fleetPath);
assert.equal(apply(fleetPath, "direct", {target: {x: 9, y: 8}}).status, 400);
assert.equal(apply(fleetPath, "start", {live: true}).status, 400);
assert.deepEqual(read(fleetPath), beforeBad);
assert.equal(runtime.dispatch({path: "/api/run", method: "POST", body: {}}).status, 404);
assert.equal(runtime.dispatch({path: fleetPath, method: "DELETE", body: null}).status, 405);
assert.equal(runtime.dispatch({path: `${fleetPath}/actions`, method: "POST", body: {action: "start"}}).status, 400);
assert.equal(runtime.dispatch({path: `${fleetPath}/actions`, method: "POST", body: {large: "x".repeat(70000)}}).status, 400);

runtime.dispose();
console.log(JSON.stringify({
  runtime: "Pyodide/WASM", version: "314.0.7", source_root: fileURLToPath(sourceRoot),
  fleet: {status: fleetDone.status, elapsed_s: fleetDone.elapsed_s,
          baseline_requests: fleetDone.metrics.baseline_requests, governed_requests: fleetDone.metrics.governed_requests},
  arm: {status: armDone.status, elapsed_s: armDone.elapsed_s, payload: armDone.payload.state},
  checked: ["RLock", "uuid4", "relative handoff import", "preset review and return", "manual teaching and repeat",
            "grip loss latch and recovery", "budget refusal", "directed target", "pause and step", "fault recovery",
            "idempotency", "stale run rejection", "input validation", "route allowlist", "request size limit"],
  physical_commands: 0, model_calls: 0, api_cloud_cost_usd: 0,
}, null, 2));

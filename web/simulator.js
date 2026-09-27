/* Relay's offline spatial simulator. The server owns all mission state and accounting. */
(() => {
  "use strict";
  // Animate only through server-recorded travel. A missing or ambiguous route snaps
  // to the authoritative endpoint instead of drawing a chord through equipment.
  function interpolateTravel(previous, robot, progress, obstacles = []) {
    const end = {x: robot.x, y: robot.y};
    if (!previous || progress >= 1) return end;
    const trail = robot.trail || [];
    let start = -1;
    for (let i = trail.length - 1; i >= 0; i--) {
      if (trail[i].x === previous.x && trail[i].y === previous.y) {start = i;break;}
    }
    if (start < 0) return end;
    const points = trail.slice(start);
    if (points.at(-1)?.x !== end.x || points.at(-1)?.y !== end.y) return end;
    const lengths = [];
    let total = 0;
    for (let i = 1; i < points.length; i++) {
      const a = points[i - 1], b = points[i];
      if (![a.x, a.y, b.x, b.y].every(Number.isFinite)) return end;
      // Slab intersection against the engine's 0.3 m obstacle clearance.
      for (const obstacle of obstacles) {
        let enter = 0, leave = 1;
        for (const [axis, size] of [["x", "width"], ["y", "height"]]) {
          const delta = b[axis] - a[axis];
          const low = obstacle[axis] - 0.3;
          const high = obstacle[axis] + obstacle[size] + 0.3;
          if (delta === 0) {
            if (a[axis] < low || a[axis] > high) {enter = 2;break;}
          } else {
            const first = (low - a[axis]) / delta, last = (high - a[axis]) / delta;
            enter = Math.max(enter, Math.min(first, last));
            leave = Math.min(leave, Math.max(first, last));
          }
        }
        if (enter <= leave) return end;
      }
      const distance = Math.hypot(b.x - a.x, b.y - a.y);
      lengths.push(distance);
      total += distance;
    }
    if (total === 0) return end;
    let remaining = total * Math.max(0, progress);
    for (let i = 0; i < lengths.length; i++) {
      if (remaining <= lengths[i] && lengths[i] > 0) {
        const ratio = remaining / lengths[i], a = points[i], b = points[i + 1];
        return {x: a.x + (b.x - a.x) * ratio, y: a.y + (b.y - a.y) * ratio};
      }
      remaining -= lengths[i];
    }
    return end;
  }
  if (typeof module !== "undefined" && module.exports) {
    module.exports = {interpolateTravel};
    if (typeof document === "undefined") return;
  }
  const $ = (id) => document.getElementById(id);
  const canvas = $("facility-map");
  const context = canvas.getContext("2d");
  const number = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
  const format = (value, digits = 0) => number(value).toLocaleString(undefined, {maximumFractionDigits: digits, minimumFractionDigits: digits});
  const words = (value) => String(value || "ready").replaceAll("_", " ");
  const clock = (value) => `${String(Math.floor(number(value) / 60)).padStart(2, "0")}:${String(Math.floor(number(value) % 60)).padStart(2, "0")}`;
  const cost = (value) => `$${number(value).toFixed(4)}`;
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let state = null;
  let previousState = null;
  let pending = false;
  let failed = false;
  let timer = null;
  let frame = null;
  let receivedAt = 0;
  let selectedTarget = null;
  let mapProjection = null;
  let lastEventSignature = "";
  let lastFleetSignature = "";

  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function allowed(action) {
    return state && Array.isArray(state.allowed_actions) && state.allowed_actions.includes(action);
  }

  function setStatus(message) {
    $("control-status").textContent = message;
  }

  function stopTimer() {
    if (timer !== null) window.clearTimeout(timer);
    timer = null;
  }

  function schedule() {
    stopTimer();
    if (!failed && !pending && !document.hidden && state?.status === "running" && allowed("step")) {
      timer = window.setTimeout(() => act("step", {dt_s: 0.5, steps: number($("speed").value, 2)}, true), 500);
    }
  }

  async function request(url, options = {}) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(url, {...options, signal: controller.signal, cache: "no-store"});
      let data;
      try { data = await response.json(); } catch (_) { throw new Error("The service returned an unreadable response."); }
      if (!response.ok) {
        const detail = typeof data.detail === "string" ? data.detail : `Request rejected (${response.status}). Check the mission state and target.`;
        const error = new Error(detail);
        error.httpStatus = response.status;
        throw error;
      }
      if (!data || !data.world || !Array.isArray(data.robots) || data.simulated !== true) {
        throw new Error("The response is not a valid simulated mission snapshot.");
      }
      return data;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("The local simulator did not respond within 12 seconds. Reconnect to read its current state.");
      throw error;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  function errorMessage(error) {
    const rejectedInput = error.httpStatus === 400 || error.httpStatus === 422;
    failed = !rejectedInput;
    stopTimer();
    $("error-text").textContent = error.message || "Unable to reach the local simulator.";
    $("error-banner").hidden = false;
    $("connection-dot").classList.toggle("connected", rejectedInput);
    $("connection-state").textContent = rejectedInput ? "Local simulator connected" : error.httpStatus ? "Simulator state needs refreshing" : "Simulator connection interrupted";
    setStatus(rejectedInput ? "Request rejected. Adjust the target or control and try again." : "Playback stopped. Reconnect to read the latest state before continuing.");
  }

  function accept(snapshot, animate = true) {
    previousState = state;
    state = snapshot;
    if (state.status !== "idle" && ["preset", "directed"].includes(state.mode)) {
      $("scenario").value = state.mode;
    }
    receivedAt = performance.now();
    failed = false;
    $("error-banner").hidden = true;
    $("connection-dot").classList.add("connected");
    $("connection-state").textContent = "Local simulator connected";
    if (!selectedTarget || previousState?.run_id !== state.run_id || state.status !== "idle") {
      const missionTarget = state.target || state.world.hazard;
      selectedTarget = {x: number(missionTarget?.x, 20), y: number(missionTarget?.y, 11)};
      $("target-x").value = selectedTarget.x;
      $("target-y").value = selectedTarget.y;
    }
    render();
    animateMap(animate);
  }

  async function connect() {
    if (pending) return;
    pending = true;
    stopTimer();
    renderControls();
    setStatus("Reading simulator state…");
    try {
      accept(await request("/api/simulator"), false);
    } catch (error) {
      errorMessage(error);
    } finally {
      pending = false;
      renderControls();
      schedule();
    }
  }

  async function act(action, payload = {}, automatic = false) {
    if (pending || failed || !state || !allowed(action)) return;
    stopTimer();
    pending = true;
    renderControls();
    if (!automatic) setStatus(`${words(action)} requested…`);
    const actionId = `ui-${window.crypto?.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`}`;
    try {
      accept(await request("/api/simulator/actions", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({run_id: state.run_id, action_id: actionId, action, ...payload}),
      }));
    } catch (error) {
      errorMessage(error);
    } finally {
      pending = false;
      renderControls();
      schedule();
    }
  }

  function renderControls() {
    const blocked = pending || failed || !state;
    const directed = $("scenario").value === "directed";
    const canStart = allowed(directed ? "direct" : "start");
    $("start").disabled = blocked || (!canStart && !allowed("resume"));
    $("start").textContent = state?.status === "paused" ? "▶ Resume mission" : directed ? "↗ Start directed mission" : "▶ Start mission";
    $("pause").disabled = blocked || !allowed("pause");
    $("stop").disabled = blocked || !allowed("stop");
    $("step").disabled = blocked || !allowed("step");
    $("reset").disabled = blocked || !allowed("reset");
    $("dispatch").disabled = blocked || !allowed("direct");
    $("inject-fault").disabled = blocked || !allowed("inject_fault");
    $("clear-fault").disabled = blocked || !allowed("clear_fault");
    $("scenario").disabled = blocked || state?.status !== "idle";
    $("speed").disabled = blocked;
    $("target-robot").disabled = blocked;
    $("target-x").disabled = blocked || !allowed("direct");
    $("target-y").disabled = blocked || !allowed("direct");
    $("fault").disabled = blocked;
    $("reconnect").disabled = pending;
    $("review-controls").hidden = state?.status !== "needs_review" || !state?.review?.required || Boolean(state?.review?.acknowledged);
    $("review").disabled = blocked || !allowed("review") || Boolean(state?.metrics?.budget_refused);
    $("review-note").textContent = state?.metrics?.budget_refused
      ? "The modeled allowance refused this analysis. Reset to restore the allowance; review cannot bypass the refusal."
      : "This fixture needs operator acknowledgement before a preview is queued. The real environment has not been declared safe.";
    $("scenario-description").textContent = directed
      ? "Set a free floor coordinate below. The rover leads, then the hexapod gathers a second view."
      : "The rover patrol discovers synthetic evidence, then the hexapod gathers a close second view.";
    if (state && !failed && !pending && $("error-banner").hidden) {
      const descriptions = {
        idle: "Ready. Start the preset or choose a directed target.",
        running: `${words(state.stage)} · advancing ${$("speed").value}× simulated time.`,
        paused: "Simulation paused. Resume or advance one second at a time.",
        needs_review: state.metrics?.budget_refused ? "Model allowance exhausted. Reset required to analyze further." : "Finding ready. Acknowledge the simulation to continue.",
        faulted: "Fault injected. Clear the fault, then resume when ready.",
        completed: "Mission complete. Review its event trail and handoff preview.",
        stopped: "Mission stopped. Reset to prepare another inspection.",
      };
      setStatus(descriptions[state.status] || words(state.stage));
    }
    $("map-instruction").textContent = allowed("direct")
      ? "⌖ Click the floor to set an inspection target"
      : state?.status === "completed" ? "✓ Mission complete · reset to inspect another target" : "Follow the scouts · routes and decisions are simulated";
  }

  function render() {
    const metrics = state.metrics || {};
    const totalDistance = state.robots.reduce((sum, robot) => sum + number(robot.distance_m), 0);
    $("metric-clock").textContent = clock(state.elapsed_s);
    $("metric-status").textContent = `${words(state.status)} · ${words(state.stage)}`;
    $("metric-distance").replaceChildren(document.createTextNode(`${format(totalDistance, 1)} `), node("em", "", "m"));
    $("metric-saved").textContent = format(metrics.avoided_requests);
    $("metric-saved-detail").textContent = number(metrics.baseline_requests) > 0
      ? `${format(metrics.request_reduction_pct)}% fewer simulated requests`
      : "Against analyzing every observation";
    $("metric-paid").textContent = `$${number(state.actual_api_cost_usd ?? metrics.actual_api_cost_usd).toFixed(2)}`;
    $("run-status").textContent = words(state.status).toUpperCase();
    $("run-status").className = `pill ${state.status}`;
    $("baseline-requests").textContent = format(metrics.baseline_requests);
    $("economy-requests").textContent = format(metrics.governed_requests);
    $("baseline-tokens").textContent = format(number(metrics.baseline_input_tokens) + number(metrics.baseline_output_tokens));
    $("economy-tokens").textContent = format(number(metrics.governed_input_tokens) + number(metrics.governed_output_tokens));
    $("baseline-cost").textContent = cost(metrics.baseline_estimated_cost_usd);
    $("economy-cost").textContent = cost(metrics.governed_estimated_cost_usd);
    $("savings-fill").style.width = `${Math.max(0, Math.min(100, number(metrics.request_reduction_pct)))}%`;
    $("economy-summary").textContent = number(metrics.observations) > 0
      ? `${format(metrics.observations)} observations · ${format(metrics.routine_filtered)} routine + ${format(metrics.duplicates_filtered)} duplicate readings filtered locally. ${format(metrics.governed_requests)} / ${format(metrics.modeled_request_allowance)} modeled requests used.`
      : "Start a mission to compare the policies against its sensor evidence.";
    $("target-x").max = number(state.world.width_m);
    $("target-y").max = number(state.world.height_m);
    renderRobots();
    renderEvents();
    renderArm();
    renderControls();
  }

  function renderRobots() {
    const signature = state.robots.map((robot) => robot.id).join("|");
    if (signature !== lastFleetSignature) {
      $("target-robot").replaceChildren(...state.robots.map((robot) => {
        const option = node("option", "", robot.name || words(robot.id));
        option.value = robot.id;
        return option;
      }));
      lastFleetSignature = signature;
    }
    $("fleet-cards").replaceChildren(...state.robots.map((robot) => {
      const isHex = robot.id === "hexapod" || robot.kind === "hexapod";
      const card = node("article", `fleet-card ${isHex ? "hexapod" : "rover"}`);
      const top = node("div", "fleet-card-top");
      const name = node("div", "fleet-name");
      name.append(node("span", "fleet-symbol", isHex ? "✳" : "▰"));
      const title = node("div");
      title.append(node("h3", "", isHex ? "Freenove hexapod" : "Intellio rover"), node("p", "", isHex ? "Six-leg crawler · simulated" : "Wheeled scout · simulated"));
      name.append(title);
      top.append(name, node("span", `fleet-status ${state.status === "faulted" ? "faulted" : ""}`, words(robot.state)));
      const telemetry = node("div", "fleet-telemetry");
      const currentSpeed = state.status === "running" && robot.state === "moving" ? robot.speed_mps : 0;
      for (const [label, value] of [["BATTERY", `${format(robot.battery_pct)}%`], ["SPEED", `${format(currentSpeed, 1)} m/s`], ["TRAVEL", `${format(robot.distance_m, 1)} m`]]) {
        const cell = node("div");
        cell.append(node("span", "", label), node("strong", "", value));
        telemetry.append(cell);
      }
      const battery = node("div", "battery-track");
      const level = node("i");
      level.style.width = `${Math.max(0, Math.min(100, number(robot.battery_pct)))}%`;
      battery.append(level);
      const position = node("div", "fleet-position");
      position.append(node("span", "", `X ${format(robot.x, 1)} / Y ${format(robot.y, 1)} m`), node("span", "", `${format(robot.heading_deg)}° HEADING`));
      const sensors = node("div", "fleet-position");
      sensors.append(node("span", "", robot.sensors?.valid === false ? "SENSOR DROPOUT" : `SIGNAL ${format(number(robot.sensors?.hazard_signal) * 100)}%`), node("span", "", robot.sensors?.nearest_obstacle_m == null ? "CLEARANCE —" : `CLEARANCE ${format(robot.sensors.nearest_obstacle_m, 1)} m`));
      card.append(top, telemetry, battery, position, sensors);
      return card;
    }));
  }

  function renderEvents() {
    const events = state.events || [];
    const signature = `${state.run_id}:${events.length}:${events.at(-1)?.sequence}`;
    if (signature === lastEventSignature) return;
    lastEventSignature = signature;
    $("event-count").textContent = `${events.length} EVENTS`;
    if (!events.length) {
      $("event-list").replaceChildren(node("li", "empty-state", "Start a mission to follow navigation, sensing, decisions, and recovery."));
      return;
    }
    $("event-list").replaceChildren(...events.slice(-60).reverse().map((event) => {
      const item = node("li");
      item.append(node("span", "event-time", clock(event.time_s)));
      const body = node("div");
      const line = node("div", "event-line");
      line.append(node("strong", "", words(event.kind)), node("span", "", event.robot_id ? words(event.robot_id).toUpperCase() : "WORKFLOW"));
      body.append(line, node("p", "event-detail", event.message));
      item.append(body);
      return item;
    }));
  }

  function renderArm() {
    const handoff = state.arm_handoff || {};
    const proposal = handoff.proposal;
    const ready = Boolean(proposal);
    $("arm-summary").textContent = ready
      ? "The simulated inspection has a handoff record. It can be reviewed as software evidence; the physical arm remains unconnected here."
      : "Inspection evidence can become a reviewed arm task. This page runs the virtual arm; physical playback is not verified.";
    $("arm-queue").replaceChildren();
    if (ready) {
      const item = node("li");
      item.append(node("strong", "", `${words(handoff.status)} · ${words(proposal.action)} → ${words(proposal.target_id)}`), document.createTextNode(`Station: ${proposal.inspection?.station_id || "inspection station"}. Preview only. No actuator command is sent.`));
      $("arm-queue").append(item);
    }
  }

  function project(x, y) {
    return {x: mapProjection.left + number(x) * mapProjection.scale, y: mapProjection.top + (mapProjection.height - number(y)) * mapProjection.scale};
  }

  function roundedRect(x, y, width, height, radius = 5) {
    context.beginPath();
    context.roundRect(x, y, width, height, radius);
  }

  function label(text, x, y, color = "#7a8d75", size = 9, centered = false) {
    context.fillStyle = color;
    context.font = `${size}px "Segoe UI", Arial, sans-serif`;
    context.textAlign = centered ? "center" : "left";
    context.fillText(text, x, y);
  }

  function linePath(points, color, width, dash = []) {
    if (!points?.length) return;
    context.beginPath();
    points.forEach((point, i) => {
      const p = project(point.x, point.y);
      if (i === 0) context.moveTo(p.x, p.y); else context.lineTo(p.x, p.y);
    });
    context.strokeStyle = color;
    context.lineWidth = width;
    context.setLineDash(dash);
    context.stroke();
    context.setLineDash([]);
  }

  function drawMap(interpolation = 1) {
    const bounds = canvas.getBoundingClientRect();
    if (bounds.width === 0 || bounds.height === 0) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const width = bounds.width;
    const height = bounds.height;
    if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
    }
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    context.clearRect(0, 0, width, height);
    context.fillStyle = "#e9eee3";
    context.fillRect(0, 0, width, height);
    if (!state) {
      label("LOADING LOCAL INSPECTION ENVIRONMENT", width / 2, height / 2, "#87967f", 10, true);
      return;
    }
    const world = state.world;
    const worldWidth = number(world.width_m, 24);
    const worldHeight = number(world.height_m, 16);
    const padding = width < 450 ? 26 : 42;
    const scale = Math.min((width - padding * 2) / worldWidth, (height - padding * 2) / worldHeight);
    mapProjection = {scale, width: worldWidth, height: worldHeight, left: (width - worldWidth * scale) / 2, top: (height - worldHeight * scale) / 2};
    const origin = project(0, worldHeight);
    const right = project(worldWidth, 0);
    context.fillStyle = "#f4f6eb";
    roundedRect(origin.x, origin.y, worldWidth * scale, worldHeight * scale, 3);
    context.fill();
    context.strokeStyle = "#becdb4";
    context.lineWidth = 2;
    context.stroke();
    context.save();
    context.beginPath();
    context.rect(origin.x, origin.y, worldWidth * scale, worldHeight * scale);
    context.clip();
    for (let x = 0; x <= worldWidth; x += 1) {
      const p = project(x, 0);
      context.beginPath();context.moveTo(p.x, origin.y);context.lineTo(p.x, right.y);
      context.strokeStyle = x % 5 === 0 ? "#d9e2ce" : "#e6ebdd";context.lineWidth = .6;context.stroke();
    }
    for (let y = 0; y <= worldHeight; y += 1) {
      const p = project(0, y);
      context.beginPath();context.moveTo(origin.x, p.y);context.lineTo(right.x, p.y);
      context.strokeStyle = y % 5 === 0 ? "#d9e2ce" : "#e6ebdd";context.lineWidth = .6;context.stroke();
    }
    // Facility geometry and routes come directly from the local metric engine.
    for (const obstacle of world.obstacles || []) {
      const topLeft = project(obstacle.x, number(obstacle.y) + number(obstacle.height));
      const obstacleWidth = number(obstacle.width) * scale;
      const obstacleHeight = number(obstacle.height) * scale;
      context.fillStyle = "#c8d2bd";
      roundedRect(topLeft.x + 3, topLeft.y + 4, obstacleWidth, obstacleHeight, 3);context.fill();
      context.fillStyle = "#dce3d0";context.strokeStyle = "#bfccb2";context.lineWidth = 1;
      roundedRect(topLeft.x, topLeft.y, obstacleWidth, obstacleHeight, 3);context.fill();context.stroke();
      context.save();context.clip();
      context.strokeStyle = "#c4d0b663";
      for (let hatch = -obstacleHeight; hatch < obstacleWidth; hatch += 9) {
        context.beginPath();context.moveTo(topLeft.x + hatch, topLeft.y);context.lineTo(topLeft.x + hatch + obstacleHeight, topLeft.y + obstacleHeight);context.stroke();
      }
      context.restore();
      if (obstacleWidth > 40 && obstacleHeight > 25) label(words(obstacle.id).toUpperCase(), topLeft.x + obstacleWidth / 2, topLeft.y + obstacleHeight / 2 + 3, "#8d9e7f", Math.min(8, obstacleWidth / 10), true);
    }
    const station = world.station;
    if (station) {
      const p = project(station.x, station.y);
      context.fillStyle = "#dfebd7";context.strokeStyle = "#8eaa7c";context.lineWidth = 1;context.setLineDash([4, 3]);
      roundedRect(p.x - scale * 1.2, p.y - scale * 1.1, scale * 2.4, scale * 2.2, 5);context.fill();context.stroke();context.setLineDash([]);
      label("STATION / HANDOFF", p.x, p.y - scale * 1.1 - 9, "#6b8c5a", width < 450 ? 7 : 9, true);
      context.fillStyle = "#a0b78c";roundedRect(p.x - 9, p.y - 9, 18, 18, 3);context.fill();
      label("S", p.x, p.y + 4, "#f8fff3", 11, true);
    }
    const hazard = world.hazard;
    if (hazard) {
      const p = project(hazard.x, hazard.y);
      const radius = Math.max(12, number(hazard.radius_m, 1.4) * scale);
      const gradient = context.createRadialGradient(p.x, p.y, 0, p.x, p.y, radius * 1.5);
      gradient.addColorStop(0, "#e8c87860");gradient.addColorStop(1, "#e8c87800");
      context.fillStyle = gradient;context.beginPath();context.arc(p.x, p.y, radius * 1.5, 0, Math.PI * 2);context.fill();
      context.strokeStyle = "#cba45e";context.setLineDash([3, 4]);context.lineWidth = 1;context.beginPath();context.arc(p.x, p.y, radius, 0, Math.PI * 2);context.stroke();context.setLineDash([]);
      context.fillStyle = "#cba65c";context.beginPath();context.arc(p.x, p.y, 4, 0, Math.PI * 2);context.fill();
      label("INSPECTION ZONE", p.x, p.y - radius - 8, "#ad8845", width < 450 ? 7 : 9, true);
    }
    for (const robot of state.robots) {
      const color = robot.id === "hexapod" ? "#7d91bf" : "#549675";
      linePath(robot.trail, `${color}88`, 3);
      linePath([{x: robot.x, y: robot.y}, ...(robot.path || [])], `${color}aa`, 1.6, [5, 5]);
      const target = robot.target;
      if (target) {
        const p = project(target.x, target.y);context.strokeStyle = color;context.lineWidth = 1;
        context.beginPath();context.arc(p.x, p.y, 6, 0, Math.PI * 2);context.stroke();
      }
    }
    if (selectedTarget && allowed("direct")) {
      const p = project(selectedTarget.x, selectedTarget.y);context.strokeStyle = "#4d7568";context.lineWidth = 1;
      context.beginPath();context.arc(p.x, p.y, 10, 0, Math.PI * 2);context.moveTo(p.x - 15, p.y);context.lineTo(p.x + 15, p.y);context.moveTo(p.x, p.y - 15);context.lineTo(p.x, p.y + 15);context.stroke();
      label("DIRECTED TARGET", p.x, p.y + 24, "#527a67", 8, true);
    }
    for (const robot of state.robots) drawRobot(robot, interpolation, scale);
    context.restore();
    for (let x = 0; x <= worldWidth; x += 5) {
      const p = project(x, 0);label(String(x), p.x, right.y + 15, "#98a58d", 8, true);
    }
    for (let y = 0; y <= worldHeight; y += 5) {
      const p = project(0, y);label(String(y), p.x - 17, p.y + 3, "#98a58d", 8, true);
    }
    $("map-scale").textContent = "5 m";
    $("map-scale").previousElementSibling.style.width = `${Math.max(20, 5 * scale)}px`;
  }

  function drawRobot(robot, interpolation, scale) {
    const previous = previousState?.run_id === state.run_id ? previousState.robots.find((item) => item.id === robot.id) : null;
    const position = interpolateTravel(previous, robot, interpolation, state.world.obstacles || []);
    const p = project(position.x, position.y);
    const isHex = robot.id === "hexapod" || robot.kind === "hexapod";
    const moving = previous && (previous.x !== robot.x || previous.y !== robot.y) && interpolation < 1;
    const size = Math.max(11, Math.min(17, scale * .68));
    const color = isHex ? "#687fb2" : "#28765c";
    context.save();
    context.translate(p.x, p.y);
    context.fillStyle = isHex ? "#9caed125" : "#5eac8330";
    context.beginPath();context.arc(0, 0, size * 2.1, 0, Math.PI * 2);context.fill();
    context.rotate(-number(robot.heading_deg) * Math.PI / 180);
    context.shadowColor = "#253d3326";context.shadowBlur = 5;context.shadowOffsetY = 3;
    if (isHex) {
      // Six independently drawn legs, with alternating tripod motion while translating.
      context.strokeStyle = color;context.lineWidth = 2.8;context.lineCap = "round";
      for (const side of [-1, 1]) for (let leg = -1; leg <= 1; leg++) {
        const gait = moving && !reducedMotion.matches ? Math.sin(interpolation * Math.PI * 4 + (leg + side) * Math.PI) * size * .16 : 0;
        context.beginPath();context.moveTo(leg * size * .48, side * size * .34);context.lineTo(leg * size * .65 + gait, side * size * .84);context.lineTo(leg * size * .96 + gait, side * size * 1.08);context.stroke();
      }
      context.fillStyle = "#f0f1f8";context.strokeStyle = color;context.lineWidth = 2;
      context.beginPath();context.ellipse(0, 0, size * .8, size * .53, 0, 0, Math.PI * 2);context.fill();context.stroke();
      context.fillStyle = color;roundedRect(-size * .35, -size * .27, size * .62, size * .54, 2);context.fill();
      context.fillStyle = "#c1d7f4";context.beginPath();context.arc(size * .65, 0, 2.7, 0, Math.PI * 2);context.fill();
    } else {
      context.fillStyle = "#355946";
      for (const side of [-1, 1]) for (const axle of [-1, 1]) {roundedRect(axle * size * .5 - size * .27, side * size * .65 - 3, size * .55, 6, 2);context.fill();}
      context.fillStyle = "#f2f7e8";context.strokeStyle = color;context.lineWidth = 2;
      roundedRect(-size * .85, -size * .55, size * 1.7, size * 1.1, 4);context.fill();context.stroke();
      context.fillStyle = color;roundedRect(-size * .5, -size * .34, size * .7, size * .68, 2);context.fill();
      context.fillStyle = "#a6dbc5";roundedRect(size * .38, -size * .3, size * .24, size * .6, 1);context.fill();
    }
    context.shadowBlur = 0;context.shadowOffsetY = 0;
    context.restore();
    label(isHex ? "HEXAPOD" : "ROVER", p.x, p.y + size * 1.65 + 8, color, 8, true);
    if (state.status === "faulted" && (robot.fault || /fault|blocked|battery|dropout/.test(robot.state))) {
      context.fillStyle = "#c7954c";context.beginPath();context.arc(p.x + size, p.y - size, 6, 0, Math.PI * 2);context.fill();label("!", p.x + size, p.y - size + 3, "#fff8df", 9, true);
    }
  }

  function animateMap(animate = true) {
    if (frame !== null) cancelAnimationFrame(frame);
    frame = null;
    if (!animate || reducedMotion.matches || !previousState || document.hidden) {drawMap();return;}
    const tick = () => {
      const progress = Math.min(1, (performance.now() - receivedAt) / 360);
      drawMap(progress);
      if (progress < 1) frame = requestAnimationFrame(tick); else frame = null;
    };
    frame = requestAnimationFrame(tick);
  }

  function readTarget() {
    if (!$("target-form").reportValidity()) return null;
    const x = Number($("target-x").value);
    const y = Number($("target-y").value);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
    selectedTarget = {x, y};
    return {target: selectedTarget};
  }

  $("start").addEventListener("click", () => {
    if (allowed("resume")) return act("resume");
    if ($("scenario").value === "directed") {
      const payload = readTarget();
      if (payload) act("direct", payload);
    } else act("start");
  });
  $("pause").addEventListener("click", () => act("pause"));
  $("stop").addEventListener("click", () => act("stop"));
  $("step").addEventListener("click", () => act("step", {dt_s: 0.5, steps: 2}));
  $("reset").addEventListener("click", () => act("reset"));
  $("review").addEventListener("click", () => act("review", {decision: "acknowledge"}));
  $("reconnect").addEventListener("click", connect);
  $("speed").addEventListener("change", () => {renderControls();schedule();});
  $("scenario").addEventListener("change", renderControls);
  $("target-form").addEventListener("submit", (event) => {event.preventDefault();const payload = readTarget();if (payload) act("direct", payload);});
  $("inject-fault").addEventListener("click", () => act("inject_fault", {robot_id: $("target-robot").value, fault: $("fault").value}));
  $("clear-fault").addEventListener("click", () => act("clear_fault"));
  for (const id of ["target-x", "target-y"]) $(id).addEventListener("input", () => {
    const x = Number($("target-x").value);const y = Number($("target-y").value);
    if (Number.isFinite(x) && Number.isFinite(y)) {selectedTarget = {x, y};drawMap();}
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!mapProjection) return;
    const rect = canvas.getBoundingClientRect();
    const x = (event.clientX - rect.left - mapProjection.left) / mapProjection.scale;
    const y = mapProjection.height - (event.clientY - rect.top - mapProjection.top) / mapProjection.scale;
    $("cursor-coordinates").textContent = x >= 0 && y >= 0 && x <= mapProjection.width && y <= mapProjection.height ? `X ${x.toFixed(1)} / Y ${y.toFixed(1)} m` : "LOCAL X / Y · METERS";
  });
  canvas.addEventListener("pointerleave", () => {$("cursor-coordinates").textContent = "LOCAL X / Y · METERS";});
  canvas.addEventListener("click", (event) => {
    if (!mapProjection || pending || failed || !allowed("direct")) return;
    const rect = canvas.getBoundingClientRect();
    const x = (event.clientX - rect.left - mapProjection.left) / mapProjection.scale;
    const y = mapProjection.height - (event.clientY - rect.top - mapProjection.top) / mapProjection.scale;
    if (x < 0 || y < 0 || x > mapProjection.width || y > mapProjection.height) return;
    selectedTarget = {x: Math.round(x * 10) / 10, y: Math.round(y * 10) / 10};
    $("target-x").value = selectedTarget.x;$("target-y").value = selectedTarget.y;
    $("scenario").value = "directed";
    renderControls();drawMap();
    setStatus(`Target set to X ${selectedTarget.x}, Y ${selectedTarget.y} m. Plan the directed inspection when ready.`);
  });
  new ResizeObserver(() => drawMap()).observe($("map-container"));
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {stopTimer();if (frame !== null) cancelAnimationFrame(frame);frame = null;}
    else {drawMap();schedule();}
  });
  window.addEventListener("pagehide", stopTimer);
  connect();
})();

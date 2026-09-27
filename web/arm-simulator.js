/* Independent virtual-arm rehearsal. No device transport or physical servo units. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const n = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
  const words = (value) => String(value || "ready").replaceAll("_", " ");
  const names = ["Base yaw", "Shoulder", "Elbow", "Wrist pitch", "Wrist roll", "Gripper"];
  const canvas = $("arm-sim-canvas"), ctx = canvas.getContext("2d");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  let state = null, previous = null, pending = false, failed = false;
  let timer = null, frame = null, receivedAt = 0, slidersReady = false;

  function element(tag, className, text) {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text !== undefined) item.textContent = text;
    return item;
  }
  const allowed = (action) => Boolean(state?.allowed_actions?.includes(action));
  function cancelTick() {if (timer !== null) window.clearTimeout(timer);timer = null;}
  function schedule() {
    cancelTick();
    if (!pending && !failed && !document.hidden && state?.status === "running" && allowed("step")) {
      timer = window.setTimeout(() => act("step", {dt_s: 0.25, steps: n($("arm-sim-speed").value, 2)}, true), 250);
    }
  }
  async function request(options = {}) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(`/api/simulator/arm${options.method ? "/actions" : ""}`, {...options, cache: "no-store", signal: controller.signal});
      let data;
      try {data = await response.json();} catch (_) {throw new Error("The arm simulator returned an unreadable response.");}
      if (!response.ok) {
        const error = new Error(typeof data.detail === "string" ? data.detail : `Arm request rejected (${response.status}).`);
        error.httpStatus = response.status;throw error;
      }
      if (data.simulated !== true || !Array.isArray(data.joints_deg) || data.joints_deg.length !== 6 || !Array.isArray(data.allowed_actions)) throw new Error("The response is not a six-joint simulated arm snapshot.");
      return data;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("Arm simulator timed out. Reconnect to read its current state.");
      throw error;
    } finally {window.clearTimeout(timeout);}
  }
  function showError(error) {
    failed = error.httpStatus !== 400 && error.httpStatus !== 422;
    cancelTick();
    $("arm-sim-error").hidden = false;
    $("arm-sim-error-text").textContent = error.message;
    $("arm-sim-status").textContent = failed ? "Playback stopped. Reconnect to read the current arm state." : "Request rejected. Adjust the virtual pose or routine and retry.";
  }
  function accept(snapshot) {
    previous = state;state = snapshot;failed = false;receivedAt = performance.now();
    $("arm-sim-error").hidden = true;
    if (!slidersReady) buildSliders();
    if (!previous || previous.run_id !== state.run_id || state.status !== "idle") {
      state.joints_deg.forEach((value, index) => {$("arm-joint-" + index).value = n(value);$("arm-joint-value-" + index).textContent = `${n(value).toFixed(0)}°`;});
    }
    render();animate();
  }
  async function connect() {
    if (pending) return;
    pending = true;cancelTick();controls();
    try {accept(await request());} catch (error) {showError(error);} finally {pending = false;controls();schedule();}
  }
  async function act(action, payload = {}, automatic = false) {
    if (pending || failed || !allowed(action)) return;
    pending = true;cancelTick();controls();
    if (!automatic) $("arm-sim-status").textContent = `${words(action)} requested…`;
    const id = window.crypto?.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    try {
      accept(await request({method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({run_id: state.run_id, action_id: `arm-ui-${id}`, action, ...payload})}));
    } catch (error) {showError(error);} finally {pending = false;controls();schedule();}
  }
  function buildSliders() {
    $("arm-sim-sliders").replaceChildren(...names.map((name, index) => {
      const block = element("div", "arm-sim-slider");
      const label = element("label", "", `J${index + 1} · ${name}`);label.htmlFor = `arm-joint-${index}`;
      const output = element("output", "", "90°");output.id = `arm-joint-value-${index}`;output.htmlFor = `arm-joint-${index}`;label.append(output);
      const input = element("input");input.id = `arm-joint-${index}`;input.type = "range";input.min = "0";input.max = "180";input.step = "1";input.value = "90";
      input.addEventListener("input", () => {output.textContent = `${n(input.value).toFixed(0)}°`;});
      const range = element("small");range.append(element("span", "", "0°"), element("span", "", "180° virtual"));
      block.append(label, input, range);return block;
    }));
    slidersReady = true;
  }
  function controls() {
    const blocked = pending || failed || !state;
    for (const [id, action] of [["pause", "pause"], ["stop", "stop"], ["step", "step"], ["reset", "reset"], ["apply", "pose"], ["record", "capture"], ["replay", "replay"], ["inject", "inject_fault"], ["clear", "clear_fault"]]) {
      $("arm-sim-" + id).disabled = blocked || !allowed(action) || (action === "replay" && !state?.recorded_routine?.length);
    }
    $("arm-sim-start").disabled = blocked || (!allowed("start") && !allowed("resume"));
    $("arm-sim-start").textContent = allowed("resume") ? "▶ Resume" : "▶ Play preset";
    $("arm-sim-speed").disabled = blocked;
    $("arm-sim-fault").disabled = blocked;
    $("arm-sim-pose-name").disabled = blocked || !allowed("capture");
    $("arm-sim-reconnect").disabled = pending;
    if (slidersReady) names.forEach((_, i) => {$("arm-joint-" + i).disabled = blocked || !allowed("pose");});
    if (state && !pending && !failed && $("arm-sim-error").hidden) {
      const descriptions = {
        idle: "Ready. Play the preset or apply and record virtual poses.",
        running: `${words(state.stage)} · ${$("arm-sim-speed").value}× simulated time.`,
        paused: "Paused. Resume or advance one half-second at a time.",
        faulted: "Synthetic fault stopped the routine. Clear it, then resume explicitly.",
        completed: "Virtual routine complete. Replay the preset or teach another pose.",
        stopped: "Stopped. Reset to prepare a new virtual routine.",
      };
      $("arm-sim-status").textContent = descriptions[state.status] || words(state.status);
    }
  }
  function render() {
    $("arm-sim-state").textContent = words(state.status).toUpperCase();$("arm-sim-state").className = `pill ${state.status}`;
    $("arm-sim-joints").replaceChildren(...names.map((name, index) => {
      const item = element("div", "arm-sim-joint");item.append(element("span", "", `J${index + 1} ${name}`), element("strong", "", `${n(state.joints_deg[index]).toFixed(1)}°`));return item;
    }));
    const waypoint = state.routine?.[state.current_waypoint];
    $("arm-sim-stage").textContent = waypoint ? `${words(waypoint.name)} · pose ${n(state.current_waypoint) + 1} of ${state.routine.length}` : words(state.stage);
    $("arm-sim-clock").textContent = `${String(Math.floor(n(state.elapsed_s) / 60)).padStart(2, "0")}:${String(Math.floor(n(state.elapsed_s) % 60)).padStart(2, "0")}`;
    $("arm-sim-progress").style.width = `${Math.max(0, Math.min(100, n(state.progress) * 100))}%`;
    $("arm-sim-payload").textContent = `Virtual marker: ${words(state.payload?.state)} · gripper ${words(state.gripper?.state)} · physical commands dispatched: 0`;
    const poses = state.recorded_routine || [];
    $("arm-sim-recorded").replaceChildren(...(poses.length ? poses.map((pose, i) => {
      const item = element("li");item.append(element("strong", "", `${i + 1}. ${pose.name}`), document.createTextNode(` · ${n(pose.duration_s).toFixed(1)} s · ${pose.joints_deg.map((value) => n(value).toFixed(0)).join(" / ")}°`));return item;
    }) : [element("li", "", "No poses recorded yet. Apply a virtual pose, then record its current angles.")]));
    $("arm-sim-events").replaceChildren(...(state.events || []).slice(-20).reverse().map((event) => {
      const item = element("li"), body = element("div"), line = element("div", "event-line");
      item.append(element("span", "event-time", `${n(event.time_s).toFixed(1)} s`));line.append(element("strong", "", words(event.kind)), element("span", "", "VIRTUAL ARM"));body.append(line, element("p", "event-detail", event.message));item.append(body);return item;
    }));
    controls();
  }
  function text(value, x, y, color = "#779368", size = 9, align = "left") {
    ctx.fillStyle = color;ctx.font = `${size}px "Segoe UI", Arial, sans-serif`;ctx.textAlign = align;ctx.fillText(value, x, y);
  }
  function circle(x, y, radius, fill, stroke) {ctx.beginPath();ctx.arc(x, y, radius, 0, Math.PI * 2);ctx.fillStyle = fill;ctx.fill();if (stroke) {ctx.strokeStyle = stroke;ctx.lineWidth = 1.5;ctx.stroke();}}
  function draw(progress = 1) {
    const bounds = canvas.getBoundingClientRect();if (!bounds.width || !bounds.height) return;
    const width = bounds.width, height = bounds.height, dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {canvas.width = Math.round(width * dpr);canvas.height = Math.round(height * dpr);}
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);ctx.clearRect(0, 0, width, height);ctx.fillStyle = "#f0f4e8";ctx.fillRect(0, 0, width, height);
    if (!state) {text("LOADING VIRTUAL ARM", width / 2, height / 2, "#91a480", 10, "center");return;}
    const prev = previous?.run_id === state.run_id ? previous : null;
    const mix = (value, old) => n(old, n(value)) + (n(value) - n(old, n(value))) * progress;
    const angles = state.joints_deg.map((value, i) => mix(value, prev?.joints_deg?.[i]));
    const links = (state.link_positions || []).map((point, i) => ({x: mix(point.x, prev?.link_positions?.[i]?.x), y: mix(point.y, prev?.link_positions?.[i]?.y), z: mix(point.z, prev?.link_positions?.[i]?.z)}));
    const yaw = (angles[0] - 90) * Math.PI / 180;
    const radial = (point) => n(point.x) * Math.cos(yaw) + n(point.y) * Math.sin(yaw);
    const worldPoints = [...links, ...Object.values(state.stations || {}), ...(state.payload?.position ? [state.payload.position] : [])];
    const minX = Math.min(-.15, ...worldPoints.map(radial)), maxX = Math.max(.75, ...worldPoints.map(radial));
    const minZ = Math.min(-.04, ...worldPoints.map((point) => n(point.z))), maxZ = Math.max(.8, ...worldPoints.map((point) => n(point.z)));
    const scale = Math.min((width - 135) / (maxX - minX), (height - 85) / (maxZ - minZ));
    const baseX = 20 - minX * scale, ground = height - 40 + minZ * scale;
    const project = (point) => ({x: baseX + radial(point) * scale, y: ground - n(point.z) * scale});
    ctx.strokeStyle = "#dbe5cf";ctx.lineWidth = .7;
    for (let x = 20; x < width; x += 25) {ctx.beginPath();ctx.moveTo(x, 25);ctx.lineTo(x, ground + 15);ctx.stroke();}
    for (let y = 25; y <= ground; y += 25) {ctx.beginPath();ctx.moveTo(20, y);ctx.lineTo(width - 20, y);ctx.stroke();}
    ctx.strokeStyle = "#b8caab";ctx.lineWidth = 1.4;ctx.beginPath();ctx.moveTo(20, ground);ctx.lineTo(width - 20, ground);ctx.stroke();
    text("SIDE PROFILE", 18, 21, "#849c74", 8);
    for (const [name, position] of Object.entries(state.stations || {})) {
      const point = project(position);ctx.fillStyle = "#dce6ce";ctx.fillRect(point.x - 15, point.y, 30, 4);text(name === "source" ? "PICK ZONE" : "PLACE ZONE", Math.max(42, Math.min(width - 42, point.x)), point.y + (name === "source" ? 20 : 32), "#96a781", 7, "center");
    }
    const points = links.map(project);
    ctx.fillStyle = "#a6bd93";ctx.beginPath();ctx.roundRect(baseX - 29, ground - 14, 58, 14, 4);ctx.fill();
    ctx.fillStyle = "#799b63";ctx.beginPath();ctx.ellipse(baseX, ground - 15, 24, 7, 0, 0, Math.PI * 2);ctx.fill();
    if (points.length) {
      ctx.strokeStyle = "#839f6d";ctx.lineWidth = 18;ctx.lineCap = "round";ctx.beginPath();ctx.moveTo(baseX, ground - 15);ctx.lineTo(points[0].x, points[0].y);ctx.stroke();
      for (let i = 1; i < points.length; i++) {
        const a = points[i - 1], b = points[i];
        ctx.strokeStyle = "#6f9060";ctx.lineWidth = i === points.length - 1 ? 11 : 18;ctx.beginPath();ctx.moveTo(a.x, a.y);ctx.lineTo(b.x, b.y);ctx.stroke();
        ctx.strokeStyle = "#c1d2b1";ctx.lineWidth = i === points.length - 1 ? 6 : 11;ctx.beginPath();ctx.moveTo(a.x, a.y);ctx.lineTo(b.x, b.y);ctx.stroke();
      }
      points.slice(0, -1).forEach((p, i) => {circle(p.x, p.y, i === 0 ? 13 : 10, "#eaf0de", "#799a67");circle(p.x, p.y, 4, "#8eaa7c");text(`J${i + 2}`, p.x - 14, p.y - 18, "#7b966c", 8);});
      const tip = points.at(-1), preTip = points.at(-2) || {x: tip.x - 1, y: tip.y};
      const direction = Math.atan2(tip.y - preTip.y, tip.x - preTip.x);
      const openness = n(state.gripper?.open_fraction, .6);
      ctx.save();ctx.translate(tip.x, tip.y);ctx.rotate(direction);ctx.strokeStyle = "#708c61";ctx.lineWidth = 3;
      for (const side of [-1, 1]) {ctx.beginPath();ctx.moveTo(0, side * 4);ctx.lineTo(12, side * (4 + openness * 8));ctx.lineTo(20, side * (3 + openness * 8));ctx.stroke();}
      if (state.payload?.state === "held") {ctx.fillStyle = "#d3a76a";ctx.fillRect(12, -5, 10, 10);}ctx.restore();
      text("J6 GRIPPER", tip.x + 8, tip.y - 18, "#8b9f79", 8);
    }
    if (state.payload?.position && state.payload.state !== "held") {
      const marker = project(state.payload.position);ctx.fillStyle = state.payload.state === "dropped" ? "#c18a68" : "#d7b477";ctx.strokeStyle = "#b39157";ctx.lineWidth = 1;ctx.beginPath();ctx.roundRect(marker.x - 6, marker.y - 12, 12, 12, 2);ctx.fill();ctx.stroke();
      text(words(state.payload.state).toUpperCase(), Math.max(42, Math.min(width - 42, marker.x)), marker.y - 19, "#a99162", 7, "center");
    }
    const dialSize = width < 430 ? 27 : 34, dialX = width - dialSize - 23;
    const dial = (angle, y, title, color) => {
      circle(dialX, y, dialSize + 10, "#f7faef", "#d7e2c9");circle(dialX, y, dialSize - 2, "#edf4e2", "#c1d3ac");
      const theta = (angle - 90) * Math.PI / 180;
      ctx.strokeStyle = color;ctx.lineWidth = 3;ctx.beginPath();ctx.moveTo(dialX, y);ctx.lineTo(dialX + Math.cos(theta) * (dialSize - 7), y + Math.sin(theta) * (dialSize - 7));ctx.stroke();circle(dialX, y, 4, color);
      text(title, dialX, y + dialSize + 24, "#81996f", 7, "center");text(`${angle.toFixed(0)}°`, dialX, y - dialSize - 17, color, 9, "center");
    };
    dial(angles[0], 67, "J1 BASE YAW", "#72976a");dial(angles[4], Math.min(height - 64, 185), "J5 WRIST ROLL", "#8d9cb8");
    if (state.status === "faulted") {text(`FAULT: ${words(state.fault).toUpperCase()}`, 18, 41, "#b1784a", 9);}
  }
  function animate() {
    if (frame !== null) cancelAnimationFrame(frame);frame = null;
    if (reducedMotion.matches || !previous || document.hidden) {draw();return;}
    const tick = () => {const progress = Math.min(1, (performance.now() - receivedAt) / 210);draw(progress);frame = progress < 1 ? requestAnimationFrame(tick) : null;};
    frame = requestAnimationFrame(tick);
  }
  $("arm-sim-start").addEventListener("click", () => act(allowed("resume") ? "resume" : "start"));
  for (const [id, action] of [["pause", "pause"], ["stop", "stop"], ["reset", "reset"], ["clear", "clear_fault"], ["replay", "replay"]]) $("arm-sim-" + id).addEventListener("click", () => act(action));
  $("arm-sim-step").addEventListener("click", () => act("step", {dt_s: 0.25, steps: 2}));
  $("arm-sim-inject").addEventListener("click", () => act("inject_fault", {fault: $("arm-sim-fault").value}));
  $("arm-sim-record").addEventListener("click", () => act("capture", {name: $("arm-sim-pose-name").value.trim() || "Virtual pose", duration_s: 2}));
  $("arm-sim-pose-form").addEventListener("submit", (event) => {event.preventDefault();act("pose", {joints_deg: names.map((_, i) => n($("arm-joint-" + i).value)), duration_s: 2});});
  $("arm-sim-speed").addEventListener("change", () => {controls();schedule();});
  $("arm-sim-reconnect").addEventListener("click", connect);
  document.addEventListener("visibilitychange", () => {if (document.hidden) {cancelTick();if (frame !== null) cancelAnimationFrame(frame);frame = null;} else {draw();schedule();}});
  window.addEventListener("pagehide", cancelTick);
  new ResizeObserver(() => draw()).observe($("arm-sim-canvas-wrap"));
  connect();
})();

"use strict";

(() => {
  const byId = (id) => document.getElementById(id);
  const controls = ["run-economy", "run-compare", "run-refusal", "run-integrations"].map(byId);
  let fixture = null;
  let busy = false;
  let activeMission = null;
  let fleetReady = false;
  let pendingMissionRequest = null;
  let missionUnavailable = false;
  const missionButtons = ["mission-start", "mission-advance", "mission-review", "mission-pause", "mission-resume", "mission-cancel"].map(byId);
  const missionLabels = {monitor: "Station observation", scout: "Scout evidence analysis", second_view: "Second observation", review: "Operator review rehearsal", announce: "Announcement rehearsal"};
  const integerFormat = new Intl.NumberFormat("en-US");
  const knownReasons = {
    below_threshold: "Below the analysis threshold",
    threshold_crossing: "New wetness event",
    alert_already_active: "Existing alert · no new analysis",
    alert_reset: "Wetness alert reset locally",
    fixed_interval: "Scheduled model check",
    budget_refused: "Analysis refused by the budget",
    missing_recording: "Recording unavailable",
    provider_or_accounting_failure: "Analysis needs review",
    unsupported_sensor_requires_review: "Sensor requires review"
  };

  function put(id, value) { byId(id).textContent = value; }
  function number(value) { return Number.isFinite(Number(value)) ? integerFormat.format(Number(value)) : "—"; }
  function money(value) {
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return "Unverified";
    const amount = Number(value);
    return "$" + amount.toFixed(amount === 0 ? 2 : 6);
  }
  function setStatus(message, error = false) {
    put("run-status", message);
    byId("run-status").classList.toggle("error", error);
  }
  function setBusy(value) {
    busy = value;
    controls.forEach((control) => { control.disabled = value || !fixture; });
    byId("create-mission").disabled = value || !fixture || !fleetReady || Boolean(pendingMissionRequest);
    missionButtons.forEach((control) => { control.disabled = value || !activeMission || missionUnavailable || Boolean(pendingMissionRequest); });
    byId("mission-retry").hidden = !pendingMissionRequest;
    byId("mission-retry").disabled = value;
    byId("budget-form").setAttribute("aria-busy", String(value));
  }
  async function getJson(url, options = {}) {
    const response = await fetch(url, { ...options, headers: { "Content-Type": "application/json", ...options.headers } });
    let body;
    try { body = await response.json(); }
    catch { throw new Error("The local service returned an unreadable response."); }
    if (!response.ok) {
      const detail = typeof body.detail === "string" ? body.detail : "Check the mission limits and local server output.";
      const error = new Error("Request failed (" + response.status + "). " + detail);
      error.status = response.status;
      throw error;
    }
    return body;
  }
  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function renderMission(mission) {
    activeMission = mission;
    missionUnavailable = false;
    byId("mission-active").hidden = false;
    put("mission-state", mission.status.replaceAll("_", " "));
    put("mission-progress", mission.progress.completed + " / " + mission.progress.total + " simulated tasks");
    const tasks = byId("mission-tasks");
    tasks.replaceChildren();
    (mission.proposed_tasks || []).forEach((task) => {
      const row = element("li");
      row.append(element("strong", "", (missionLabels[task.task_id] || task.role) + " · " + task.status.replaceAll("_", " ")));
      row.append(element("span", "", (task.device_id || (task.role === "human_review" ? "Operator rehearsal" : "No device assigned")) + " · " + task.why_assigned));
      if (task.summary) row.append(element("span", "", task.summary));
      tasks.append(row);
    });
    const allowed = new Set(mission.allowed_actions || []);
    const actionButtons = {start: "mission-start", complete_task: "mission-advance", simulate_review: "mission-review", pause: "mission-pause", resume: "mission-resume", cancel: "mission-cancel"};
    Object.entries(actionButtons).forEach(([action, id]) => { byId(id).hidden = !allowed.has(action); });
    put("mission-advance", mission.next_task?.task_id === "scout" ? "Analyze synthetic evidence" : "Simulate next task");
    put("mission-record", JSON.stringify(mission, null, 2));
    const blockers = mission.blockers?.length ? " Review required: " + mission.blockers.join(", ").replaceAll("_", " ") + "." : "";
    put("mission-plan-status", mission.mode + " mission at " + mission.station_id + " / " + mission.target_id + "." + blockers + " No physical commands. Records last until this service restarts.");
  }
  async function sendPendingMissionRequest() {
    const request = pendingMissionRequest;
    if (!request) return;
    try {
      const mission = await getJson(request.url, {method: "POST", body: JSON.stringify(request.body)});
      renderMission(mission);
      pendingMissionRequest = null;
    } catch (error) {
      // A write can succeed even when its response does not reach this browser.
      // Reconcile by the original action ID, never by the apparent next task.
      let snapshot = null;
      let readError = null;
      try { snapshot = await getJson("/api/missions/" + encodeURIComponent(request.missionId)); }
      catch (failure) { readError = failure; }
      if (snapshot) {
        renderMission(snapshot);
        if (snapshot.events?.some((event) => event.action_id === request.body.action_id)) {
          pendingMissionRequest = null;
          put("mission-plan-status", "Recovered the saved mission after a response interruption. The original request was recorded; no task was repeated. " + byId("mission-plan-status").textContent);
          return;
        }
      }
      const message = error instanceof Error ? error.message : "Mission request failed.";
      if (error.status >= 400 && error.status < 500 && (snapshot || readError?.status === 404)) {
        // An explicit rejection resolves this attempt. Keep any saved record,
        // but disable its commands if the service confirms it no longer exists.
        pendingMissionRequest = null;
        if (readError?.status === 404 && activeMission?.mission_id === request.missionId) missionUnavailable = true;
        put("mission-plan-status", message + (snapshot ? " Current mission state was reloaded; choose the next action shown." : missionUnavailable ? " This mission is unavailable. Its last record is retained below; plan a new simulation." : " No new mission state was confirmed."));
      } else {
        put("mission-plan-status", message + " The request outcome or current mission state is unconfirmed. Retry the pending request to reuse its original ID. Other mission controls stay paused until it is resolved.");
      }
    }
  }
  byId("mission-retry").addEventListener("click", async () => {
    if (busy || !pendingMissionRequest) return;
    setBusy(true);
    try { await sendPendingMissionRequest(); }
    finally { setBusy(false); }
  });
  async function loadMissionInventory() {
    try {
      const data = await getJson("/api/missions/inventory");
      const selector = byId("mission-scout");
      data.inventory.filter((device) => device.capabilities.includes("scout")).forEach((device) => {
        const option = element("option", "", device.name + (device.available ? " · simulated" : " · unavailable"));
        option.value = device.device_id;
        selector.append(option);
      });
      fleetReady = true;
      put("mission-plan-status", "Declared fleet loaded. Plan a preset or directed inspection; all hardware remains disconnected.");
      setBusy(busy);
    } catch {
      put("mission-plan-status", "The mission planner is unavailable. Existing sensor replays remain available below.");
    }
  }
  byId("mission-plan-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || pendingMissionRequest || !fleetReady || !byId("mission-plan-form").reportValidity()) return;
    setBusy(true);
    try {
      const missionId = "mission-" + crypto.randomUUID();
      pendingMissionRequest = {url: "/api/missions", missionId, body: {
        mission_id: missionId, action_id: "create-" + crypto.randomUUID(),
        mode: byId("mission-mode").value, station_id: byId("mission-station").value,
        target_id: byId("mission-target").value, scout_id: byId("mission-scout").value || null,
        second_view: byId("mission-second-view").checked
      }};
      await sendPendingMissionRequest();
    } catch (error) { put("mission-plan-status", error instanceof Error ? error.message : "Planning failed."); }
    finally { setBusy(false); }
  });
  async function missionAction(action) {
    if (busy || pendingMissionRequest || missionUnavailable || !activeMission) return;
    if (action === "complete_task" && activeMission.next_task?.task_id === "scout" && !byId("budget-form").reportValidity()) return;
    setBusy(true);
    try {
      let payload = {};
      if (action === "simulate_review") payload = {decision: "acknowledge"};
      if (action === "complete_task") {
        const task = activeMission.next_task;
        if (!task) throw new Error("No simulated task is ready.");
        payload = {task_id: task.task_id, outcome: "completed", summary: "Simulated task only; no physical device operated."};
        if (task.task_id === "scout") {
          const scenario = configuredScenario(false);
          scenario.mission_id = activeMission.mission_id;
          scenario.station_id = activeMission.station_id;
          const run = await getJson("/api/run", {method: "POST", body: JSON.stringify({scenario, strategy: "economy"})});
          byId("comparison-panel").hidden = true;
          renderRun(run);
          const budgetDenied = run.events.some((item) => item.reason === "budget_refused");
          payload.outcome = budgetDenied ? "budget_refused" : run.outcome !== "complete" ? "needs_review" : run.findings.some((item) => item.status === "suspected_hazard") ? "suspected_hazard" : "completed";
          payload.summary = "Mock analysis of " + scenario.observations.length + " synthetic station readings: " + payload.outcome.replaceAll("_", " ") + ". No camera image or physical scout was used.";
        }
      }
      pendingMissionRequest = {
        url: "/api/missions/" + encodeURIComponent(activeMission.mission_id) + "/actions",
        missionId: activeMission.mission_id,
        body: {action_id: action + "-" + crypto.randomUUID(), action, payload}
      };
      await sendPendingMissionRequest();
    } catch (error) { put("mission-plan-status", error instanceof Error ? error.message : "Mission action failed."); }
    finally { setBusy(false); }
  }
  Object.entries({"mission-start": "start", "mission-advance": "complete_task", "mission-review": "simulate_review", "mission-pause": "pause", "mission-resume": "resume", "mission-cancel": "cancel"})
    .forEach(([id, action]) => byId(id).addEventListener("click", () => missionAction(action)));
  function svgElement(tag, attributes) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
    return node;
  }
  function drawFixture(scenario) {
    const chart = byId("sensor-chart");
    chart.replaceChildren();
    const samples = scenario.observations.filter((observation) => Number.isFinite(observation.value_milli));
    if (!samples.length) return;
    const end = Math.max(1, ...samples.map((sample) => sample.timestamp_seconds));
    const x = (time) => 30 + time / end * 660;
    const y = (value) => 115 - Math.max(0, Math.min(1000, value)) / 1000 * 92;
    [0, 500, 1000].forEach((value) => {
      chart.append(svgElement("line", { x1: 30, x2: 690, y1: y(value), y2: y(value), stroke: "#e0e5d9", "stroke-width": 1 }));
    });
    chart.append(svgElement("line", { x1: 30, x2: 690, y1: y(700), y2: y(700), stroke: "#a79d72", "stroke-width": 1, "stroke-dasharray": "5 5" }));
    const points = samples.map((sample) => x(sample.timestamp_seconds) + "," + y(sample.value_milli));
    chart.append(svgElement("polygon", { points: ["30,115", ...points, "690,115"].join(" "), fill: "#dbeadf", opacity: ".72" }));
    chart.append(svgElement("polyline", { points: points.join(" "), fill: "none", stroke: "#146d5f", "stroke-width": "2.5", "stroke-linejoin": "round", "stroke-linecap": "round" }));
    samples.forEach((sample, index) => {
      chart.append(svgElement("circle", { cx: x(sample.timestamp_seconds), cy: y(sample.value_milli), r: 3, fill: "#146d5f", stroke: "#f6f7f1", "stroke-width": 1.5 }));
      if (index % 2 === 0 || index === samples.length - 1) {
        const label = svgElement("text", { x: x(sample.timestamp_seconds), y: 139, "text-anchor": "middle", fill: "#78836f", "font-family": "Segoe UI, sans-serif", "font-size": 10 });
        label.textContent = sample.timestamp_seconds + "s";
        chart.append(label);
      }
    });
    chart.setAttribute("aria-label", "Synthetic normalized wetness samples: " + samples.map((sample) => sample.value_milli + " at " + sample.timestamp_seconds + " seconds").join(", "));
    put("scenario-details", scenario.observations.length + " labeled samples · " + scenario.duration_seconds + "s scenario");
  }
  function configuredScenario(refusal) {
    const scenario = structuredClone(fixture);
    scenario.budget = {
      max_requests: refusal ? 0 : Number(byId("max-requests").value),
      max_tokens: Number(byId("max-tokens").value),
      max_usd: byId("max-usd").value
    };
    return scenario;
  }
  function showTimeline(run) {
    const list = byId("timeline");
    list.replaceChildren();
    const findings = new Map((run.findings || []).map((finding) => [finding.event_id, finding]));
    (run.events || []).forEach((event) => {
      const finding = findings.get(event.event_id);
      const needsReview = finding?.status === "needs_review";
      const item = element("li", "timeline-item");
      item.append(element("span", "event-time", number(event.timestamp_seconds) + "s"));
      const content = element("div");
      const heading = element("div", "event-title");
      heading.append(element("span", "", knownReasons[event.reason] || event.reason || "Observation"));
      heading.append(element("span", "event-tag " + (needsReview ? "tag-review" : event.decision === "analyze" ? "tag-analyze" : ""), needsReview ? "NEEDS REVIEW" : event.decision === "analyze" ? "ANALYSIS" : "KEPT LOCAL"));
      content.append(heading);
      if (finding) {
        content.append(element("p", "event-description", finding.summary));
        if (finding.recommended_action) content.append(element("p", "event-description", finding.recommended_action));
      }
      content.append(element("div", "event-id", event.event_id));
      if (event.local_alarm) content.append(element("p", "alarm-note", "Local wetness alarm is active at this observation."));
      item.append(content);
      list.append(item);
    });
    byId("timeline-empty").hidden = Boolean(run.events?.length);
  }
  function renderRun(run, raw = run) {
    const accounting = run.accounting || {};
    put("metric-requests", number(accounting.requests));
    put("metric-request-detail", number(accounting.new_requests) + " new · " + number(accounting.replayed_requests) + " replayed");
    put("metric-tokens", number(accounting.tokens));
    put("metric-token-detail", "Mock usage · " + (run.strategy === "baseline" ? "fixed-interval" : "economy") + " policy");
    put("metric-estimated", money(accounting.estimated_usd));
    put("metric-paid", money(accounting.actual_paid_usd));
    put("metric-paid-detail", accounting.actual_paid_usd === null ? "Provider invoice not verified" : "Mock run · no paid API calls");
    put("strategy-label", run.strategy === "baseline" ? "FIXED INTERVAL" : "ECONOMY");
    const review = run.outcome === "needs_review";
    put("outcome-heading", review ? "Human review needed." : "Replay complete.");
    put("outcome-description", review
      ? "An analysis could not complete. Evidence stays visible; a refused model call does not clear a local hazard."
      : "The simulated decisions are recorded below. A completed replay does not establish that a physical hazard is resolved.");
    put("provider-mode", run.provider_mode === "mock" ? "Mock · local" : run.provider_mode || "Unverified");
    put("audit-status", run.audit_verified === true ? "Verified in local store" : run.audit_verified === false ? "Verification failed" : "Unverified");
    const evaluation = run.evaluation || {};
    put("detection-status", evaluation.available ? number(evaluation.detected_hazard_episodes) + " / " + number(evaluation.labeled_hazard_episodes) : "Unavailable");
    put("detection-delay", evaluation.available && evaluation.detection_latency_seconds?.length ? evaluation.detection_latency_seconds.map((delay) => number(delay) + "s").join(", ") : "No detection recorded");
    if (run.limits) put("run-limits", "This run: " + number(run.limits.max_requests) + " requests / " + number(run.limits.max_tokens) + " tokens / " + money(run.limits.max_usd) + " estimated allowance.");
    put("raw-result", JSON.stringify(raw, null, 2));
    byId("raw-details").hidden = false;
    showTimeline(run);
  }
  function renderComparison(result) {
    const baseline = result.baseline;
    const economy = result.economy;
    const rows = byId("comparison-rows");
    rows.replaceChildren();
    const detected = (run) => run.evaluation?.available ? number(run.evaluation.detected_hazard_episodes) + " / " + number(run.evaluation.labeled_hazard_episodes) : "Unavailable";
    const delay = (run) => run.evaluation?.detection_latency_seconds?.length ? run.evaluation.detection_latency_seconds.map((value) => number(value) + "s").join(", ") : "No detection";
    [
      ["Accepted requests", number(baseline.accounting.requests), number(economy.accounting.requests)],
      ["Simulated tokens", number(baseline.accounting.tokens), number(economy.accounting.tokens)],
      ["Estimated model USD", money(baseline.accounting.estimated_usd), money(economy.accounting.estimated_usd)],
      ["Actual paid API USD", money(baseline.accounting.actual_paid_usd), money(economy.accounting.actual_paid_usd)],
      ["Labeled events detected", detected(baseline), detected(economy)],
      ["Detection delay", delay(baseline), delay(economy)],
      ["Run outcome", baseline.outcome, economy.outcome]
    ].forEach((values) => {
      const row = element("tr");
      values.forEach((value, index) => {
        const cell = element(index === 0 ? "th" : "td", "", value);
        if (index === 0) cell.scope = "row";
        row.append(cell);
      });
      rows.append(row);
    });
    const savings = result.savings || {};
    put("comparison-summary", result.comparison_complete
      ? number(savings.requests_avoided) + " fewer model requests (" + number(savings.request_reduction_percent) + "%) on the same synthetic evidence. Check detection results alongside cost."
      : "One or both policies need review. These partial runs are not a completed savings comparison.");
    put("comparison-status", result.comparison_complete ? "COMPLETED REPLAYS" : "PARTIAL COMPARISON");
    put("environmental-note", result.environmental_claim || "This replay does not measure energy or carbon savings.");
    byId("comparison-panel").hidden = false;
    renderRun(economy, result);
  }
  async function run(mode) {
    if (busy || !fixture || !byId("budget-form").reportValidity()) return;
    setBusy(true);
    const comparison = mode === "compare";
    setStatus(comparison ? "Running both policies on identical synthetic observations…" : mode === "refusal" ? "Testing a zero-request allowance. No paid calls or physical motion…" : "Running the local economy policy…");
    try {
      const result = await getJson(comparison ? "/api/compare" : "/api/run", {
        method: "POST",
        body: JSON.stringify({ scenario: configuredScenario(mode === "refusal"), strategy: "economy" })
      });
      if (comparison) renderComparison(result);
      else { byId("comparison-panel").hidden = true; renderRun(result); }
      setStatus(comparison
        ? "Comparison returned. Accounting cards and the decision trail show the economy run; the table shows both policies."
        : mode === "refusal"
          ? "Refusal test returned with a zero-request allowance. Inspect the outcome and local alarm in the decision trail."
          : "Local replay returned. Repeating the same evidence may reuse its recorded result; new and replayed requests are shown separately.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "The local request failed.", true);
    } finally { setBusy(false); }
  }
  byId("budget-form").addEventListener("submit", (event) => { event.preventDefault(); run("economy"); });
  byId("run-compare").addEventListener("click", () => run("compare"));
  byId("run-refusal").addEventListener("click", () => run("refusal"));
  byId("run-integrations").addEventListener("click", async () => {
    if (busy || !fixture) return;
    setBusy(true);
    put("integration-status", "Running the six adapters with synthetic evidence…");
    try {
      const result = await getJson("/api/integrations/demo", {method: "POST"});
      const trail = byId("integration-trail");
      trail.replaceChildren();
      (result.steps || []).forEach((step) => {
        const row = element("li");
        row.append(element("strong", "", step.provider));
        row.append(element("span", "", (step.status || "completed") + " · mock"));
        trail.append(row);
      });
      put("integration-json", JSON.stringify(result, null, 2));
      byId("integration-details").hidden = false;
      put("integration-status", "Replay returned. Evidence below is simulated; no live cloud writes, generated audio, or blockchain transaction.");
    } catch (error) {
      put("integration-status", error instanceof Error ? error.message : "Replay failed.");
    } finally { setBusy(false); }
  });

  async function initialize() {
    try {
      const [health, scenario] = await Promise.all([getJson("/health"), getJson("/scenarios/leak.json")]);
      if (!health || !Array.isArray(scenario.observations)) throw new Error("The local service did not return a valid scenario.");
      fixture = scenario;
      byId("max-requests").value = scenario.budget.max_requests;
      byId("max-tokens").value = scenario.budget.max_tokens;
      byId("max-usd").value = scenario.budget.max_usd;
      drawFixture(scenario);
      put("connection-status", "Mission service available");
      setStatus("Synthetic fixture loaded. Choose economy, compare both policies, or test refusal.");
      setBusy(false);
      await loadMissionInventory();
    } catch (error) {
      put("connection-status", "Mission service unavailable");
      put("scenario-details", "Scenario could not load");
      setStatus("Start scripts/start-demo.ps1 from the project, then reload this page. " + (error instanceof Error ? error.message : ""), true);
    }
  }
  initialize();
})();

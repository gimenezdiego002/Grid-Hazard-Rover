import { useEffect, useMemo, useRef, useState } from "react";
import {
  Battery,
  Camera,
  CheckCircle2,
  CircleStop,
  Cpu,
  Droplets,
  MapPin,
  Pause,
  Play,
  Radio,
  RotateCcw,
  ShieldAlert,
  Wifi,
  X,
  Zap,
} from "lucide-react";
import { humanize, type Hazard } from "./contracts";

const stages = [
  "Mission ready",
  "Walking corridor",
  "Replaying fixture evidence",
  "Reviewing fixture evidence",
  "Report preview ready",
] as const;
const STAGE_DURATION_MS = 1800;
const MISSION_DURATION_MS = (stages.length - 1) * STAGE_DURATION_MS;

export default function RoverDemo({ hazards }: { hazards: Hazard[] }) {
  const [running, setRunning] = useState(false);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [selectedEvidence, setSelectedEvidence] = useState<Hazard | null>(null);
  const elapsedRef = useRef(0);
  const lastTick = useRef<number | null>(null);
  const timerRef = useRef<number | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const stage = Math.min(stages.length - 1, Math.floor(elapsedMs / STAGE_DURATION_MS));

  function stopClock() {
    if (timerRef.current !== null) window.clearInterval(timerRef.current);
    timerRef.current = null;
    lastTick.current = null;
  }

  function advanceClock() {
    if (lastTick.current === null) return;
    const now = performance.now();
    const delta = Math.max(0, now - lastTick.current);
    lastTick.current = now;
    elapsedRef.current = Math.min(MISSION_DURATION_MS, elapsedRef.current + delta);
    setElapsedMs(elapsedRef.current);
    if (elapsedRef.current >= MISSION_DURATION_MS) {
      stopClock();
      setRunning(false);
    }
  }

  useEffect(() => {
    if (!running) return;
    lastTick.current = performance.now();
    const timer = window.setInterval(advanceClock, 100);
    timerRef.current = timer;
    return () => {
      window.clearInterval(timer);
      if (timerRef.current === timer) {
        timerRef.current = null;
        lastTick.current = null;
      }
    };
  }, [running]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!selectedEvidence || !dialog) return;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog.showModal();
    return () => {
      if (dialog.open) dialog.close();
      if (opener?.isConnected) opener.focus();
    };
  }, [selectedEvidence]);

  const evidence = useMemo(() => {
    const source = hazards.slice(0, 3);
    if (source.length) return source;
    return [
      {
        id: "demo-water",
        hazard_type: "standing_water",
        severity: 4,
        confidence: 0.91,
        description: "Simulated water near a work corridor.",
        timestamp: "2026-09-27T12:00:00Z",
        image_url: null,
        location: { type: "Point" as const, coordinates: [-80.352, 25.765] as [number, number] },
        metadata: { demo: true },
      },
    ];
  }, [hazards]);

  function reset() {
    stopClock();
    elapsedRef.current = 0;
    setRunning(false);
    setElapsedMs(0);
    setSelectedEvidence(null);
  }

  function toggleRunning() {
    if (running) {
      advanceClock();
      stopClock();
      setRunning(false);
    } else if (elapsedRef.current < MISSION_DURATION_MS) {
      setRunning(true);
    }
  }

  const progress = Math.round((stage / (stages.length - 1)) * 100);
  const capturedCount = Math.min(evidence.length, Math.max(0, stage - 1));
  const elapsed = Math.floor(elapsedMs / 1000);
  const missionTime = `${String(Math.floor(elapsed / 60)).padStart(2, "0")}:${String(elapsed % 60).padStart(2, "0")}`;

  return (
    <section className="rover-demo" aria-label="Simulated crawler mission">
      <div className="rover-demo-head">
        <div>
          <span className="eyebrow">SIMULATED STREET INSPECTION</span>
          <h2>See what the crawler would observe.</h2>
          <p>No robot is moving. This sequence replays synthetic evidence; it makes no model calls or report submissions.</p>
          <div className="street-technologies" aria-label="Street scene technologies">
            <span>React</span><span>TypeScript</span><span>SVG</span>
          </div>
        </div>
        <span className="simulation-chip">Simulation</span>
      </div>

      <div className="rover-demo-grid">
        <div className="street-scene">
          <div className="city-skyline" aria-hidden="true">
            <i /><i /><i /><i /><i />
          </div>
          <div className="street-road" aria-hidden="true">
            <span /><span /><span /><span />
          </div>
          {evidence.map((hazard, index) => {
            const position = evidence.length === 1 ? 50 : 18 + (64 * index) / (evidence.length - 1);
            const captured = index < capturedCount;
            return (
            <button
              key={position}
              className={`inspection-point point-${index + 1} ${captured ? "captured" : ""}`}
              aria-label={`Inspection point ${index + 1}${captured ? ": fixture evidence available" : ""}`}
              style={{ left: `${position}%` }}
              disabled={!captured || !hazard}
              onClick={() => hazard && setSelectedEvidence(hazard)}
            >
              {captured ? <CheckCircle2 size={15} /> : <Camera size={15} />}
            </button>
          )})}
          <div
            className={`hexapod ${running ? "walking" : ""}`}
            style={{ left: `${8 + stage * 20}%` }}
            aria-label={`Crawler: ${stages[stage]}`}
          >
            <svg viewBox="0 0 120 70" role="img" aria-label="Freenove hexapod illustration">
              <g className="legs">
                <path d="M42 40 18 58 5 56M48 44 30 65 18 67M78 40 101 58 116 55M72 44 90 65 103 67" />
                <path d="M43 33 17 32 5 40M77 33 103 32 116 40" />
              </g>
              <rect x="37" y="22" width="46" height="28" rx="9" />
              <circle cx="49" cy="36" r="4" />
              <circle cx="71" cy="36" r="4" />
              <rect x="54" y="14" width="14" height="10" rx="3" />
            </svg>
            <small>FNK0052</small>
          </div>
          <div className="mission-status">
            <span className={running ? "live-dot" : "status-dot"} />
            <strong>{stages[stage]}</strong>
            <small>Step {stage + 1} of {stages.length}</small>
          </div>
          <div className="rover-telemetry" aria-label="Simulated rover telemetry">
            <span><Wifi size={12} /> {running ? "Simulation running" : "Simulation idle"}</span>
            <span><Battery size={12} /> Sample battery 87%</span>
            <span><Cpu size={12} /> No inference</span>
            <strong>T+{missionTime}</strong>
          </div>
        </div>

        <aside className="mission-panel">
          <div className="mission-panel-head">
            <div><span className="eyebrow">INSPECTION TIMELINE</span><h3>NW Miami corridor</h3></div>
            <span className={`mission-live ${running ? "active" : ""}`}><Radio size={11} /> {stage === stages.length - 1 ? "Complete" : running ? "Simulated" : "Paused / ready"}</span>
          </div>
          <div className="mission-progress">
            <div><span>Mission progress</span><strong>{progress}%</strong></div>
            <i><b style={{ width: `${progress}%` }} /></i>
          </div>
          <div className="mission-mini-stats">
            <span><strong>{capturedCount}</strong> Evidence records</span>
            <span><strong>{evidence.slice(0, capturedCount).filter((item) => item.severity >= 4).length}</strong> Priority</span>
            <span><strong>{stage + 1}</strong> / {stages.length}</span>
          </div>
          <div className="mission-controls">
            <button
              className="primary"
              onClick={toggleRunning}
              disabled={stage === stages.length - 1}
            >
              {stage === stages.length - 1 ? <><CheckCircle2 size={16} /> Completed</> : running ? <><Pause size={16} /> Pause</> : <><Play size={16} /> {elapsedMs > 0 ? "Continue" : "Start demo"}</>}
            </button>
            <button type="button" className="secondary street-reset" aria-describedby="street-reset-help" onClick={reset}>
              <RotateCcw size={16} /> Reset street
            </button>
          </div>
          <p id="street-reset-help" className="street-reset-help">
            Rewinds this replay and clears opened evidence. Fleet and arm simulations keep their state.
          </p>
          <ol className="mission-steps">
            {stages.map((label, index) => (
              <li key={label} className={stage === index ? "active" : stage > index ? "done" : ""}>
                <span>{stage > index ? <CheckCircle2 size={14} /> : index + 1}</span>
                <div>{label}<small>{index === 0 ? "Simulated readiness" : index === stages.length - 1 ? "Preview only · no submission" : `Illustrated waypoint ${index}`}</small></div>
              </li>
            ))}
          </ol>
          <div className="safety-note">
            <CircleStop size={17} /> Physical actuation remains disabled. A supervised hardware test is still required.
          </div>
        </aside>
      </div>

      <div className="inspection-heading">
        <div>
          <h3>Inspection evidence</h3>
          <p>Unlocked records show synthetic fixture times, coordinates and assumed confidence. They are not measurements or newly captured photographs.</p>
        </div>
        <span>{capturedCount} of {evidence.length} fixture records</span>
      </div>
      {capturedCount === 0 && <p className="muted">Start the rehearsal to reveal its fixture evidence.</p>}
      <div className="inspection-gallery">
        {evidence.slice(0, capturedCount).map((hazard, index) => (
          <article className="inspection-card" key={hazard.id}>
            <button className="inspection-preview" onClick={() => setSelectedEvidence(hazard)} aria-label={`Open evidence for ${humanize(hazard.hazard_type)}`}>
              {hazard.image_url ? (
                <img src={hazard.image_url} alt={`Crawler evidence: ${humanize(hazard.hazard_type)}`} />
              ) : (
                <div className={`evidence-placeholder scene-${index % 3}`}>
                  {hazard.hazard_type.includes("water") || hazard.hazard_type.includes("flood") ? (
                    <Droplets size={36} />
                  ) : hazard.hazard_type.includes("cable") || hazard.hazard_type.includes("pole") ? (
                    <Zap size={36} />
                  ) : (
                    <ShieldAlert size={36} />
                  )}
                  <span>Photo preview unavailable</span>
                </div>
              )}
            </button>
            <div className="inspection-card-body">
              <div>
                <span className={`badge ${hazard.severity >= 4 ? "high" : "moderate"}`}>
                  Severity {hazard.severity}/5
                </span>
                <small>Point {index + 1}</small>
              </div>
              <h4>{humanize(hazard.hazard_type)}</h4>
              <p>{hazard.description || "Crawler observation awaiting review."}</p>
              <footer>
                <span><MapPin size={13} /> {hazard.location.coordinates.map((value) => value.toFixed(4)).join(", ")}</span>
                <span>{Math.round(hazard.confidence * 100)}% assumed fixture confidence</span>
              </footer>
            </div>
          </article>
        ))}
      </div>
      {selectedEvidence && (
        <dialog ref={dialogRef} className="evidence-modal" aria-label="Inspection evidence detail" onCancel={(event) => { event.preventDefault(); setSelectedEvidence(null); }} onClick={(event) => { if (event.target === event.currentTarget) setSelectedEvidence(null); }}>
          <article onClick={(event) => event.stopPropagation()}>
            <button className="icon-button evidence-close" aria-label="Close evidence" onClick={() => setSelectedEvidence(null)}><X size={18} /></button>
            {selectedEvidence.image_url ? (
              <img src={selectedEvidence.image_url} alt={`Inspection evidence: ${humanize(selectedEvidence.hazard_type)}`} />
            ) : (
              <div className="evidence-modal-placeholder"><Camera size={42} /><span>No retained image URL for this observation</span></div>
            )}
            <div className="evidence-modal-copy">
              <span className={`badge ${selectedEvidence.severity >= 4 ? "high" : "moderate"}`}>Severity {selectedEvidence.severity}/5</span>
              <h2>{humanize(selectedEvidence.hazard_type)}</h2>
              <p>{selectedEvidence.description || "Crawler observation awaiting review."}</p>
              <dl>
                <dt>Synthetic coordinates</dt><dd>{selectedEvidence.location.coordinates.join(", ")} <small>[longitude, latitude] · fixture location, not the local floor map</small></dd>
                <dt>Fixture time</dt><dd>{new Date(selectedEvidence.timestamp).toLocaleString()}</dd>
                <dt>Assumed fixture confidence</dt><dd>{Math.round(selectedEvidence.confidence * 100)}% · human review required; no model ran</dd>
              </dl>
            </div>
          </article>
        </dialog>
      )}
    </section>
  );
}

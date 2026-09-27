import { useEffect, useMemo, useState } from "react";
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
  "Scanning street",
  "Capturing evidence",
  "Report delivered",
] as const;

export default function RoverDemo({ hazards }: { hazards: Hazard[] }) {
  const [running, setRunning] = useState(false);
  const [stage, setStage] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [selectedEvidence, setSelectedEvidence] = useState<Hazard | null>(null);

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => {
      setStage((current) => {
        if (current >= stages.length - 1) {
          setRunning(false);
          return current;
        }
        return current + 1;
      });
    }, 1800);
    return () => window.clearInterval(timer);
  }, [running]);

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setElapsed((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [running]);

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
    setRunning(false);
    setStage(0);
    setElapsed(0);
    setSelectedEvidence(null);
  }

  const progress = Math.round((stage / (stages.length - 1)) * 100);
  const capturedCount = Math.min(evidence.length, Math.max(0, stage - 1));
  const missionTime = `${String(Math.floor(elapsed / 60)).padStart(2, "0")}:${String(elapsed % 60).padStart(2, "0")}`;

  return (
    <section className="rover-demo" aria-label="Simulated crawler mission">
      <div className="rover-demo-head">
        <div>
          <span className="eyebrow">SIMULATED STREET INSPECTION</span>
          <h2>See what the crawler would observe.</h2>
          <p>No robot is moving. This sequence demonstrates the future evidence flow.</p>
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
          {[18, 50, 82].map((position, index) => {
            const captured = index < capturedCount;
            const hazard = evidence[index];
            return (
            <button
              key={position}
              className={`inspection-point point-${index + 1} ${captured ? "captured" : ""}`}
              aria-label={`Inspection point ${index + 1}${captured ? ": evidence captured" : ""}`}
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
            <span><Wifi size={12} /> {running ? "Connected" : "Standby"}</span>
            <span><Battery size={12} /> 87%</span>
            <span><Cpu size={12} /> AI ready</span>
            <strong>T+{missionTime}</strong>
          </div>
        </div>

        <aside className="mission-panel">
          <div className="mission-panel-head">
            <div><span className="eyebrow">INSPECTION TIMELINE</span><h3>NW Miami corridor</h3></div>
            <span className={`mission-live ${running ? "active" : ""}`}><Radio size={11} /> {running ? "Live" : "Standby"}</span>
          </div>
          <div className="mission-progress">
            <div><span>Mission progress</span><strong>{progress}%</strong></div>
            <i><b style={{ width: `${progress}%` }} /></i>
          </div>
          <div className="mission-mini-stats">
            <span><strong>{capturedCount}</strong> Photos</span>
            <span><strong>{evidence.slice(0, capturedCount).filter((item) => item.severity >= 4).length}</strong> Priority</span>
            <span><strong>{stage + 1}</strong> / {stages.length}</span>
          </div>
          <div className="mission-controls">
            <button
              className="primary"
              onClick={() => setRunning((value) => !value)}
              disabled={stage === stages.length - 1}
            >
              {running ? <><Pause size={16} /> Pause</> : <><Play size={16} /> {stage ? "Continue" : "Start demo"}</>}
            </button>
            <button className="secondary" onClick={reset}>
              <RotateCcw size={16} /> Reset
            </button>
          </div>
          <ol className="mission-steps">
            {stages.map((label, index) => (
              <li key={label} className={stage === index ? "active" : stage > index ? "done" : ""}>
                <span>{stage > index ? <CheckCircle2 size={14} /> : index + 1}</span>
                <div>{label}<small>{index === 0 ? "Safety checks" : index === stages.length - 1 ? "Canonical hazard pipeline" : `Waypoint ${index}`}</small></div>
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
          <p>Each photo stays tied to its capture point, time, coordinates, and classification.</p>
        </div>
        <span>{evidence.length} observation{evidence.length === 1 ? "" : "s"}</span>
      </div>
      <div className="inspection-gallery">
        {evidence.map((hazard, index) => (
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
                <span>{Math.round(hazard.confidence * 100)}% confidence</span>
              </footer>
            </div>
          </article>
        ))}
      </div>
      {selectedEvidence && (
        <div className="evidence-modal" role="dialog" aria-modal="true" aria-label="Inspection evidence detail" onClick={() => setSelectedEvidence(null)}>
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
                <dt>Coordinates</dt><dd>{selectedEvidence.location.coordinates.join(", ")} <small>[longitude, latitude]</small></dd>
                <dt>Captured</dt><dd>{new Date(selectedEvidence.timestamp).toLocaleString()}</dd>
                <dt>Model confidence</dt><dd>{Math.round(selectedEvidence.confidence * 100)}% · human review required</dd>
              </dl>
            </div>
          </article>
        </div>
      )}
    </section>
  );
}


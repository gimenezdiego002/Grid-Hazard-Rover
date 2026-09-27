import { useMemo, useState } from "react";
import { ArrowLeft, BellRing, Building2, CalendarClock, ChevronRight, ShieldCheck } from "lucide-react";
import MapView from "./MapView";
import { humanize, type Selection, type Snapshot } from "./contracts";
import WorkspaceSwitcher from "./WorkspaceSwitcher";

export default function CompanyPortal({ data, onExit, onOpenRover }: { data: Snapshot; onExit: () => void; onOpenRover: () => void }) {
  const utilities = [...new Set(data.projects.map((project) => project.utility))];
  const [utility, setUtility] = useState(utilities[0] || "Your company");
  const [selected, setSelected] = useState<Selection | null>(null);
  const scoped = useMemo(() => {
    const projects = data.projects.filter((project) => project.utility === utility);
    const projectIds = new Set(projects.map((project) => project.id));
    const matches = data.matches.filter(
      (match) =>
        (match.left_kind === "project" && projectIds.has(match.left_id)) ||
        (match.right_kind === "project" && projectIds.has(match.right_id)),
    );
    const risks = data.risk_cells.filter((risk) => risk.project_ids.some((id) => projectIds.has(id)));
    const hazardIds = new Set(risks.flatMap((risk) => risk.hazard_ids));
    const recordIds = new Set(risks.flatMap((risk) => risk.record_ids));
    return {
      projects,
      matches,
      risk_cells: risks,
      hazards: data.hazards.filter((hazard) => hazardIds.has(hazard.id)),
      records: data.records.filter((record) => recordIds.has(record.id)),
    };
  }, [data, utility]);
  const priority = [...scoped.risk_cells].sort((a, b) => b.score - a.score)[0];

  return (
    <div className="company-shell">
      <header className="company-header">
        <div className="company-brand"><span>F</span><div><strong>FieldSight</strong><small>Company portal preview</small></div></div>
        <WorkspaceSwitcher
          mode="company"
          onSelect={(mode) => {
            if (mode === "operations") onExit();
            if (mode === "rover") onOpenRover();
          }}
        />
        <div className="company-header-actions">
          <select aria-label="Company portal utility" value={utility} onChange={(event) => setUtility(event.target.value)}>
            {utilities.map((name) => <option key={name}>{name}</option>)}
          </select>
          <button className="secondary" onClick={onExit}><ArrowLeft size={16} /> Operations workspace</button>
        </div>
      </header>
      <main className="company-main">
        <div className="company-welcome">
          <div><span className="eyebrow">YOUR INFRASTRUCTURE VIEW</span><h1>Good morning, {utility}.</h1><p>See what needs attention near your planned work.</p></div>
          <span className="portal-preview">Demo-scoped preview</span>
        </div>
        <section className="company-kpis">
          <article><Building2 /><span>Your projects</span><strong>{scoped.projects.length}</strong><small>Visible to this workspace</small></article>
          <article><BellRing /><span>Needs attention</span><strong>{scoped.risk_cells.filter((risk) => risk.score >= 60).length}</strong><small>High and critical areas</small></article>
          <article><ShieldCheck /><span>Rover findings</span><strong>{scoped.hazards.length}</strong><small>Related inspection evidence</small></article>
          <article><CalendarClock /><span>Project connections</span><strong>{scoped.matches.length}</strong><small>Nearby work and schedules</small></article>
        </section>
        <section className="company-map-layout">
          <MapView data={scoped} selected={selected} onSelect={setSelected} />
          <aside className="company-priority">
            <span className="eyebrow">WHAT NEEDS ATTENTION</span>
            {priority ? <>
              <div className={`portal-risk risk-${priority.level.toLowerCase()}`}><strong>{priority.score.toFixed(0)}</strong><span>{priority.level}<small>Risk score</small></span></div>
              <h2>Review this project area.</h2>
              <ul>{priority.reasons.slice(0, 4).map((reason) => <li key={reason}>{reason}</li>)}</ul>
              <button className="primary" onClick={() => setSelected({ kind: "risk", id: priority.id })}>Show on map <ChevronRight size={16} /></button>
            </> : <div className="empty"><ShieldCheck size={30} />No high-priority risk area is associated with this company.</div>}
          </aside>
        </section>
        <section className="company-projects">
          <div className="section-title"><div><h2>Your planned work</h2><p>Clear schedules and nearby coordination signals.</p></div></div>
          <div className="portal-project-grid">
            {scoped.projects.map((project) => <button key={project.id} onClick={() => setSelected({ kind: "project", id: project.id })}>
              <span className="badge neutral">{humanize(project.status || "schedule unknown")}</span>
              <h3>{project.title}</h3>
              <p>{project.description || "No project description supplied."}</p>
              <small>{project.start_date || "Start unknown"} → {project.end_date || "End unknown"}</small>
            </button>)}
          </div>
        </section>
      </main>
    </div>
  );
}


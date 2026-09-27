import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowUpRight,
  Bot,
  Building2,
  Camera,
  ChevronRight,
  Database,
  Layers3,
  Map,
  Network,
  PhoneCall,
  RefreshCw,
  Search,
  ShieldAlert,
  X,
} from "lucide-react";
import MapView from "./MapView";
import Upload from "./Upload";
import Calls from "./Calls";
import CompanyPortal from "./CompanyPortal";
import Fleet from "./Fleet";
import WorkspaceSwitcher, { type WorkspaceMode } from "./WorkspaceSwitcher";
import { request } from "./api";
import {
  distance,
  fixture,
  humanize,
  timeline,
  type Snapshot,
  type Selection,
  type Kind,
} from "./contracts";
const empty: Snapshot = {
  projects: [],
  records: [],
  hazards: [],
  matches: [],
  risk_cells: [],
};
type Page = "Overview" | "Coordination" | "Field hazards" | "Robot fleet" | "AI calls" | "Data sources";
const navigation = [
  { label: "Overview", page: "Overview", icon: Map },
  { label: "Project connections", page: "Coordination", icon: Network },
  { label: "Rover findings", page: "Field hazards", icon: Camera },
  { label: "Robot fleet", page: "Robot fleet", icon: Bot },
  { label: "Call reports", page: "AI calls", icon: PhoneCall },
  { label: "Evidence & sources", page: "Data sources", icon: Database },
] as const;
const pageTitle: Record<Page, string> = {
  Overview: "A clearer view of what’s ahead.",
  Coordination: "Project connections",
  "Field hazards": "Rover findings",
  "Robot fleet": "Robot fleet & simulation",
  "AI calls": "AI call reports",
  "Data sources": "Evidence & sources",
};
const safeUrl = (url: string | null) =>
  url && /^https?:\/\//i.test(url) ? url : undefined;
export default function App() {
  const [data, setData] = useState<Snapshot>(empty),
    [page, setPage] = useState<Page>("Overview"),
    [selected, setSelected] = useState<Selection | null>(null),
    [query, setQuery] = useState(""),
    [filter, setFilter] = useState("all"),
    [busy, setBusy] = useState(true),
    [error, setError] = useState(""),
    [updated, setUpdated] = useState<Date | null>(null),
    [upload, setUpload] = useState(false),
    [companyPortal, setCompanyPortal] = useState(false);
  const load = useCallback(async (signal?: AbortSignal) => {
    setBusy(true);
    setError("");
    try {
      const snapshot = await request<Snapshot>("/api/demo-summary", { signal });
      if (signal?.aborted) return;
      setData(snapshot);
      setUpdated(new Date());
    } catch (e) {
      if (!signal?.aborted)
        setError(e instanceof Error ? e.message : "Unable to load data");
    } finally {
      if (!signal?.aborted) setBusy(false);
    }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);
  const select = useCallback((s: Selection) => setSelected(s), []);
  const name = (kind: Kind, id: string) =>
    kind === "project"
      ? (data.projects.find((p) => p.id === id)?.title ?? id)
      : kind === "record"
        ? (data.records.find((r) => r.id === id)?.title ?? id)
        : humanize(data.hazards.find((h) => h.id === id)?.hazard_type ?? id);
  const utilityPairs = data.matches.filter(
    (m) => m.left_kind === "project" && m.right_kind === "project",
  );
  const risks = [...data.risk_cells].sort((a, b) => b.score - a.score);
  const risk =
    selected?.kind === "risk"
      ? data.risk_cells.find((r) => r.id === selected.id)
      : !selected
        ? risks[0]
        : undefined;
  const match =
    selected?.kind === "match"
      ? data.matches.find((m) => m.id === selected.id)
      : undefined;
  const entity =
    selected?.kind === "project"
      ? data.projects.find((p) => p.id === selected.id)
      : selected?.kind === "record"
        ? data.records.find((r) => r.id === selected.id)
        : selected?.kind === "hazard"
          ? data.hazards.find((h) => h.id === selected.id)
          : undefined;
  const fixtureCount = [
    ...data.projects,
    ...data.records,
    ...data.hazards,
  ].filter(fixture).length;
  const matches = data.matches
    .filter(
      (m) =>
        (filter === "all" ||
          (filter === "utility"
            ? m.left_kind === "project" && m.right_kind === "project"
            : m.right_kind === filter || m.left_kind === filter)) &&
        `${name(m.left_kind, m.left_id)} ${name(m.right_kind, m.right_id)} ${timeline(m)} ${m.distance_tier}`
          .toLowerCase()
          .includes(query.toLowerCase()),
    )
    .sort((a, b) => a.distance_m - b.distance_m);
  function exportSnapshot() {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "grid-hazard-rover-snapshot.json";
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  if (companyPortal) {
    return (
      <CompanyPortal
        data={data}
        onExit={() => setCompanyPortal(false)}
        onOpenRover={() => {
          setCompanyPortal(false);
          setPage("Robot fleet");
        }}
      />
    );
  }
  function selectWorkspace(mode: WorkspaceMode) {
    if (mode === "company") setCompanyPortal(true);
    if (mode === "rover") setPage("Robot fleet");
    if (mode === "operations" && page === "Robot fleet") setPage("Overview");
  }
  const detail = (
    <aside className="detail">
      <div className="section-head">
        <span className="eyebrow">COORDINATION INTELLIGENCE</span>
        {selected && (
          <button
            className="icon-button"
            aria-label="Clear selection"
            onClick={() => setSelected(null)}
          >
            <X size={16} />
          </button>
        )}
      </div>
      {risk ? (
        <>
          <div className="risk-heading">
            <span className={`badge ${risk.level.toLowerCase()}`}>
              {risk.level}
            </span>
            <span className="muted">Coordination Risk Index</span>
          </div>
          <div className="score">
            {risk.score.toFixed(0)}
            <span>/100</span>
            <Activity size={40} />
          </div>
          <h2>Understand the overlap.</h2>
          <p className="muted">
            Deterministic scoring across distance, schedules, and local
            infrastructure evidence.
          </p>
          <div className="components">
            {Object.entries(risk.components).map(([key, value]) => (
              <div key={key}>
                <div>
                  <span>{humanize(key)}</span>
                  <strong>{value} pts</strong>
                </div>
                <div className="bar">
                  <span
                    style={{
                      width: `${Math.min(100, (value / ({ distance: 40, timeline: 25, hazard: 20, public_infrastructure: 15 }[key] ?? 100)) * 100)}%`,
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
          <h3>Why this area matters</h3>
          <ul className="reasons">
            {risk.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
          <h3>Related utility projects</h3>
          {risk.project_ids.map((id) => (
            <button
              key={id}
              className="related"
              onClick={() => select({ kind: "project", id })}
            >
              {name("project", id)}
              <ChevronRight size={16} />
            </button>
          ))}
          <button
            className="secondary wide"
            onClick={() => {
              setPage("Coordination");
              setFilter("all");
              setQuery("");
            }}
          >
            Explore coordination matches <ArrowUpRight size={16} />
          </button>
        </>
      ) : match ? (
        <>
          <span className="badge neutral">
            {match.left_kind} ↔ {match.right_kind}
          </span>
          <h2>{name(match.left_kind, match.left_id)}</h2>
          <p>with {name(match.right_kind, match.right_id)}</p>
          <div className="score small">{distance(match.distance_m)}</div>
          <p>{humanize(match.distance_tier)} · Closest-point distance</p>
          <div className="notice">{timeline(match)}</div>
          <p className="muted">
            {match.timeline_overlap === null
              ? "Insufficient date information. This is not treated as a confirmed schedule conflict."
              : "Schedule relationship is calculated by the backend, independently of spatial distance."}
          </p>
          {[
            { kind: match.left_kind, id: match.left_id },
            { kind: match.right_kind, id: match.right_id },
          ].map((s, i) => (
            <button key={i} className="related" onClick={() => select(s)}>
              {name(s.kind, s.id)}
              <ChevronRight size={16} />
            </button>
          ))}
        </>
      ) : entity ? (
        <>
          <span className="badge neutral">
            {selected?.kind}
            {fixture(entity) ? " · Demo fixture" : ""}
          </span>
          <h2>
            {"title" in entity ? entity.title : humanize(entity.hazard_type)}
          </h2>
          <p>{entity.description || "No description provided."}</p>
          {"severity" in entity ? (
            <>
              <div className="score small">
                {entity.severity}
                <span>/5 severity</span>
              </div>
              <p>
                {Math.round(entity.confidence * 100)}% model confidence · Human
                review required
              </p>
              <p className="muted">
                Observed {new Date(entity.timestamp).toLocaleString()}
              </p>
              {safeUrl(entity.image_url) && (
                <a
                  href={safeUrl(entity.image_url)}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open source image ↗
                </a>
              )}
            </>
          ) : (
            <>
              <dl>
                <dt>{"utility" in entity ? "Utility" : "Source"}</dt>
                <dd>{"utility" in entity ? entity.utility : entity.source}</dd>
                <dt>Start date</dt>
                <dd>{entity.start_date ?? "Unknown"}</dd>
                <dt>End date</dt>
                <dd>{entity.end_date ?? "Unknown"}</dd>
                <dt>Status</dt>
                <dd>{entity.status ?? "Not provided"}</dd>
              </dl>
              {safeUrl(entity.source_url) && (
                <a
                  href={safeUrl(entity.source_url)}
                  target="_blank"
                  rel="noreferrer"
                >
                  View public source ↗
                </a>
              )}
            </>
          )}
          <h3>Geometry</h3>
          <p className="muted">
            {entity.location.type} · WGS84 longitude, latitude
          </p>
          <code className="entity-id">{entity.id}</code>
        </>
      ) : (
        <div className="empty">
          <Layers3 />
          <h3>No risk areas yet</h3>
          <p>Load project data to explore calculated coordination risks.</p>
        </div>
      )}
    </aside>
  );
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setPage("Overview");
          }}
        >
          <span className="brand-icon">
            <Layers3 size={24} />
          </span>
          <span>
            GRID<span className="brand-sub">HAZARD ROVER</span>
          </span>
        </a>
        <div className="workspace">
          <span className="live-dot" /> Miami-Dade workspace
          <small>UTILITY COORDINATION</small>
        </div>
        <nav>
          {navigation.map(({ label, page: targetPage, icon: Icon }) => (
            <button
              key={label}
              className={page === targetPage ? "nav-item active" : "nav-item"}
              onClick={() => {
                setPage(targetPage);
                setQuery("");
                setFilter("all");
              }}
            >
              <Icon size={19} />
              {label}
              {targetPage === "Field hazards" && (
                <span className="nav-count">{data.hazards.length}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-note">
          <ShieldAlert size={22} />
          <strong>
            Better coordination.
            <br />
            Safer infrastructure.
          </strong>
          <p>Connect planned work with what’s happening on the ground.</p>
        </div>
        <div className="sidebar-footer">
          <span className="avatar">MD</span>
          <div>
            Operations workspace<small>Grid Hazard Rover</small>
          </div>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <span className="breadcrumb">
            Workspace <ChevronRight size={14} /> <strong>{page}</strong>
          </span>
          <WorkspaceSwitcher
            mode={page === "Robot fleet" ? "rover" : "operations"}
            onSelect={selectWorkspace}
          />
          <div className="top-actions">
            <span className={`connection ${error ? "offline" : ""}`}>
              <i />
              {busy
                ? "Syncing…"
                : error
                  ? "API unavailable"
                  : updated
                    ? "API data loaded"
                    : "Not connected"}
            </span>
            <button
              className="icon-button"
              aria-label="Refresh dashboard"
              disabled={busy}
              onClick={() => void load()}
            >
              <RefreshCw size={17} className={busy ? "spin" : ""} />
            </button>
            <button className="primary" onClick={() => setUpload(true)}>
              <Camera size={17} /> Upload photo
            </button>
          </div>
        </header>
        <div className="content">
          <div className="page-heading">
            <div>
              <span className="eyebrow">SEE THE CONNECTIONS. ACT EARLIER.</span>
              <h1>{pageTitle[page]}</h1>
              <p>
                {page === "Overview"
                  ? "Utility projects, public works, and field hazards. One shared picture."
                  : page === "Coordination"
                    ? "Find spatial intersections and understand schedule uncertainty."
                    : page === "Field hazards"
                      ? "Field observations classified by Gemini, ready for human review."
                      : page === "AI calls"
                        ? "Review AI-assisted caller reports and route company follow-up."
                      : page === "Robot fleet"
                        ? "Monitor declared devices and rehearse a safe crawler inspection."
                      : "Trace your evidence. Know what is real, synthetic, or still unknown."}
              </p>
            </div>
            <button
              className="secondary"
              disabled={!updated}
              onClick={exportSnapshot}
            >
              <ArrowDownToLine size={16} /> Export data
            </button>
          </div>
          {error && (
            <div role="alert" className="error">
              {error}{" "}
              {updated
                ? "Showing the last successful snapshot."
                : "Start the backend on port 8000, then refresh."}
            </div>
          )}
          {fixtureCount > 0 && (
            <div className="fixture-note">
              <Database size={15} />
              {fixtureCount} demo fixtures in this snapshot. Synthetic inputs
              are labeled; do not interpret them as confirmed utility plans.
            </div>
          )}
          <section className="kpis" aria-label="Snapshot metrics">
            {[
              {
                label: "Utility projects",
                value: data.projects.length,
                sub: "Planned infrastructure",
                icon: Building2,
              },
              {
                label: "Project connections",
                value: utilityPairs.length,
                sub: "Nearby or crossing work",
                icon: Network,
              },
              {
                label: "Priority risk areas",
                value: risks.filter((r) => r.score >= 60).length,
                sub: "High + critical risk",
                icon: ShieldAlert,
              },
              {
                label: "Field hazards",
                value: data.hazards.length,
                sub: `${data.records.length} public records in context`,
                icon: Camera,
              },
            ].map(({ label, value, sub, icon: Icon }) => (
              <div className="kpi" key={label}>
                <div>
                  <span>{label}</span>
                  <Icon size={18} />
                </div>
                <strong>{busy && !updated ? "—" : value}</strong>
                <small>{sub}</small>
              </div>
            ))}
          </section>
          {page === "Overview" ? (
            <>
              <div className="section-title">
                <div>
                  <h2>Coordination map</h2>
                  <p>
                    Explore infrastructure and the places where plans intersect.
                  </p>
                </div>
                <span className="muted">
                  {updated
                    ? `Updated ${updated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
                    : "Awaiting data"}
                </span>
              </div>
              <div className="map-layout">
                <MapView data={data} selected={selected} onSelect={select} />
                {detail}
              </div>
              <div className="section-title">
                <div>
                  <h2>Areas to pay attention to</h2>
                  <p>
                    Ranked by the backend’s explainable Coordination Risk Index.
                  </p>
                </div>
              </div>
              <div className="risk-list">
                {risks.map((r, index) => (
                  <button
                    key={r.id}
                    className={`risk-card ${risk?.id === r.id ? "chosen" : ""}`}
                    onClick={() => select({ kind: "risk", id: r.id })}
                  >
                    <span className="risk-number">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <div>
                      <strong>
                        {r.project_ids
                          .map((id) => name("project", id))
                          .join(" × ") || "Coordination area"}
                      </strong>
                      <small>
                        {r.match_ids.length} related matches ·{" "}
                        {r.hazard_ids.length} hazards
                      </small>
                    </div>
                    <span className={`badge ${r.level.toLowerCase()}`}>
                      {r.level}
                    </span>
                    <b>{r.score.toFixed(0)}</b>
                    <ArrowUpRight size={18} />
                  </button>
                ))}
                {!risks.length && (
                  <p className="empty">
                    {busy
                      ? "Loading coordination analysis…"
                      : "No risk areas in the current dataset."}
                  </p>
                )}
              </div>
            </>
          ) : page === "Coordination" ? (
            <>
              <div className="filters">
                <label className="search">
                  <Search size={17} />
                  <input
                    aria-label="Search matches"
                    placeholder="Search projects, records, schedules…"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </label>
                <select
                  aria-label="Relationship filter"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                >
                  <option value="all">All relationships</option>
                  <option value="utility">Utility ↔ utility</option>
                  <option value="record">Public record enrichment</option>
                  <option value="hazard">Hazard enrichment</option>
                </select>
                <span className="muted">{matches.length} matches</span>
              </div>
              <div className="table-layout">
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Relationship</th>
                        <th>Distance</th>
                        <th>Schedule</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {matches.map((m) => (
                        <tr
                          key={m.id}
                          className={
                            selected?.id === m.id ? "selected-row" : ""
                          }
                        >
                          <td>
                            <button
                              className="text-button"
                              onClick={() =>
                                select({ kind: "match", id: m.id })
                              }
                            >
                              {name(m.left_kind, m.left_id)}
                              <small>↔ {name(m.right_kind, m.right_id)}</small>
                            </button>
                            <span className="table-kind">
                              {m.left_kind} / {m.right_kind}
                            </span>
                          </td>
                          <td>{distance(m.distance_m)}</td>
                          <td>
                            <span
                              className={`badge ${m.timeline_overlap === null ? "neutral" : m.timeline_overlap ? "moderate" : "low"}`}
                            >
                              {timeline(m)}
                            </span>
                          </td>
                          <td>
                            <button
                              className="icon-button"
                              aria-label={`View match ${m.id} on map`}
                              onClick={() => {
                                select({ kind: "match", id: m.id });
                                setPage("Overview");
                              }}
                            >
                              <ArrowUpRight size={17} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!matches.length && (
                    <div className="empty">
                      No matches found. Try a different filter.
                    </div>
                  )}
                </div>
                {detail}
              </div>
            </>
          ) : page === "Field hazards" ? (
            <div className="table-layout">
              <div className="hazard-grid">
                {data.hazards.map((h) => (
                  <button
                    key={h.id}
                    className="hazard-card"
                    onClick={() => select({ kind: "hazard", id: h.id })}
                  >
                    <div className="hazard-art">
                      <ShieldAlert size={40} />
                      <span
                        className={`badge ${h.severity >= 4 ? "high" : "moderate"}`}
                      >
                        Severity {h.severity}/5
                      </span>
                    </div>
                    <div className="hazard-body">
                      <span className="eyebrow">
                        {fixture(h) ? "DEMO FIXTURE" : "FIELD OBSERVATION"}
                      </span>
                      <h3>{humanize(h.hazard_type)}</h3>
                      <p>{h.description || "No description available."}</p>
                      <small>
                        {Math.round(h.confidence * 100)}% model confidence
                      </small>
                      <div className="hazard-footer">
                        {new Date(h.timestamp).toLocaleDateString()}
                        <ArrowUpRight size={18} />
                      </div>
                    </div>
                  </button>
                ))}
                {!data.hazards.length && (
                  <div className="empty">
                    No hazards yet. Upload a field photograph to begin.
                  </div>
                )}
              </div>
              {detail}
            </div>
          ) : page === "Robot fleet" ? (
            <Fleet hazards={data.hazards} />
          ) : page === "AI calls" ? (
            <Calls />
          ) : (
            <>
              <div className="source-banner">
                <Database size={28} />
                <div>
                  <h2>Evidence, not assumptions.</h2>
                  <p>
                    Counts reflect the active API snapshot. A successful data
                    fetch does not independently verify MongoDB or Gemini
                    readiness.
                  </p>
                </div>
              </div>
              <div className="source-grid">
                {[
                  {
                    title: "Utility construction",
                    items: data.projects,
                    description:
                      "Core project geometries and planned schedules.",
                  },
                  {
                    title: "Public infrastructure",
                    items: data.records,
                    description:
                      "Normalized public records from the ingestion pipeline.",
                  },
                  {
                    title: "Rover observations",
                    items: data.hazards,
                    description:
                      "Canonical hazards with severity and model confidence.",
                  },
                ].map(({ title, items, description }) => (
                  <article className="source-card" key={title}>
                    <Layers3 size={22} />
                    <h3>{title}</h3>
                    <strong>{items.length}</strong>
                    <p>{description}</p>
                    <span className="badge neutral">
                      {items.filter(fixture).length} labeled fixtures
                    </span>
                  </article>
                ))}
              </div>
              <div className="filters">
                <label className="search">
                  <Search size={17} />
                  <input
                    aria-label="Search source data"
                    placeholder="Search project or public record…"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </label>
              </div>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Project / record</th>
                      <th>Source</th>
                      <th>Schedule</th>
                      <th>Provenance</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...data.projects, ...data.records]
                      .filter((item) =>
                        `${item.title} ${"utility" in item ? item.utility : item.source}`
                          .toLowerCase()
                          .includes(query.toLowerCase()),
                      )
                      .map((item) => (
                        <tr
                          key={`${"utility" in item ? "project" : "record"}:${item.id}`}
                        >
                          <td>
                            <button
                              className="text-button"
                              onClick={() => {
                                select({
                                  kind:
                                    "utility" in item ? "project" : "record",
                                  id: item.id,
                                });
                                setPage("Overview");
                              }}
                            >
                              {item.title}
                            </button>
                          </td>
                          <td>
                            {"utility" in item ? item.utility : item.source}
                          </td>
                          <td>
                            {item.start_date ?? "Unknown"} →{" "}
                            {item.end_date ?? "Unknown"}
                          </td>
                          <td>
                            <span className="badge neutral">
                              {fixture(item)
                                ? "Demo fixture"
                                : "Not labeled synthetic"}
                            </span>
                            {safeUrl(item.source_url) && (
                              <a
                                className="source-link"
                                href={safeUrl(item.source_url)}
                                target="_blank"
                                rel="noreferrer"
                              >
                                Source ↗
                              </a>
                            )}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
              <p className="muted">
                Every synthetic item is labeled. Live provider and physical-device claims require separate evidence.
              </p>
            </>
          )}
          <footer className="page-footer">
            <span>
              <Layers3 size={14} /> GRID HAZARD ROVER
            </span>
            <span>Explainable coordination. Human decisions.</span>
          </footer>
        </div>
      </main>
      {upload && (
        <Upload onClose={() => setUpload(false)} onSaved={() => void load()} />
      )}
    </div>
  );
}

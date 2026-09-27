import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Headphones,
  LogOut,
  MapPin,
  MessageSquareText,
  PhoneCall,
  RefreshCw,
} from "lucide-react";
import { request } from "./api";
import {
  humanize,
  type CallReport,
  type CallReviewStatus,
  type CallSummary,
} from "./contracts";

const TOKEN_KEY = "fieldsight-call-access";

export default function Calls() {
  const [token, setToken] = useState(() => sessionStorage.getItem(TOKEN_KEY) || "");
  const [draft, setDraft] = useState("");
  const [calls, setCalls] = useState<CallSummary[]>([]);
  const [selected, setSelected] = useState<CallReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const headers = token ? { Authorization: `Bearer ${token}` } : undefined;

  async function load(activeToken = token) {
    if (!activeToken) return;
    setBusy(true);
    setError("");
    try {
      setCalls(
        await request<CallSummary[]>("/api/calls", {
          headers: { Authorization: `Bearer ${activeToken}` },
        }),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load calls");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void load();
  }, []); // The token is intentionally loaded once from this browser session.

  function unlock(event: React.FormEvent) {
    event.preventDefault();
    const value = draft.trim();
    if (!value) return;
    sessionStorage.setItem(TOKEN_KEY, value);
    setToken(value);
    setDraft("");
    void load(value);
  }

  async function openCall(id: string) {
    setBusy(true);
    setError("");
    try {
      setSelected(await request<CallReport>(`/api/calls/${encodeURIComponent(id)}`, { headers }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load call");
    } finally {
      setBusy(false);
    }
  }

  async function review(status: CallReviewStatus) {
    if (!selected) return;
    setBusy(true);
    try {
      const updated = await request<CallReport>(
        `/api/calls/${encodeURIComponent(selected.conversation_id)}/review`,
        {
          method: "PATCH",
          headers: { ...headers, "Content-Type": "application/json" },
          body: JSON.stringify({ status, note: selected.reviewer_note }),
        },
      );
      setSelected(updated);
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to update review");
    } finally {
      setBusy(false);
    }
  }

  if (!token) {
    return (
      <section className="call-unlock">
        <PhoneCall size={34} />
        <div>
          <span className="eyebrow">AFFILIATED COMPANY ACCESS</span>
          <h2>Open the AI call review queue</h2>
          <p>
            Enter the server-issued company token. It stays in this browser session and is
            never compiled into the application.
          </p>
          <form onSubmit={unlock} className="call-token-form">
            <input
              type="password"
              aria-label="Company call access token"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              autoComplete="off"
              placeholder="Company access token"
            />
            <button className="primary" type="submit">Open queue</button>
          </form>
        </div>
      </section>
    );
  }

  return (
    <section className="call-workspace">
      <div className="call-toolbar">
        <div>
          <span className="eyebrow">ELEVENLABS CALL INTAKE</span>
          <h2>Company follow-up queue</h2>
          <p>Caller reports remain unverified until a person reviews them.</p>
        </div>
        <div className="call-actions">
          <button className="secondary" disabled={busy} onClick={() => void load()}>
            <RefreshCw size={16} className={busy ? "spin" : ""} /> Refresh
          </button>
          <button
            className="icon-button"
            aria-label="Lock call queue"
            onClick={() => {
              sessionStorage.removeItem(TOKEN_KEY);
              setToken("");
              setCalls([]);
              setSelected(null);
            }}
          >
            <LogOut size={17} />
          </button>
        </div>
      </div>
      {error && <div className="error" role="alert">{error}</div>}
      <div className="call-layout">
        <div className="call-list">
          {calls.map((call) => (
            <button
              key={call.conversation_id}
              className={selected?.conversation_id === call.conversation_id ? "call-card chosen" : "call-card"}
              onClick={() => void openCall(call.conversation_id)}
            >
              <div className="call-card-top">
                <span className={`badge call-${call.analysis.urgency}`}>
                  {call.analysis.urgency}
                </span>
                <span className="muted">{new Date(call.ended_at).toLocaleString()}</span>
              </div>
              <strong>{call.company_name || "Unassigned company"}</strong>
              <p>{call.analysis.summary}</p>
              <small>{humanize(call.analysis.category)} · {humanize(call.review_status)}</small>
            </button>
          ))}
          {!calls.length && !busy && (
            <div className="empty">
              <PhoneCall size={28} />
              No completed calls have reached this workspace.
            </div>
          )}
        </div>
        <aside className="call-detail">
          {!selected ? (
            <div className="empty">
              <MessageSquareText size={32} />
              Select a call to inspect its transcript and follow-up recommendation.
            </div>
          ) : (
            <>
              <div className="call-card-top">
                <span className={`badge call-${selected.analysis.urgency}`}>
                  {selected.analysis.urgency} priority
                </span>
                <span className="badge neutral">{humanize(selected.review_status)}</span>
              </div>
              <h2>{selected.company_name || "Unassigned company"}</h2>
              <p>{selected.analysis.summary}</p>
              <div className="call-facts">
                <span><Clock3 size={15} /> {selected.duration_seconds ?? "Unknown"} seconds</span>
                <span><MapPin size={15} /> {selected.analysis.location_text || "Location not collected"}</span>
                <span><Headphones size={15} /> {humanize(selected.recording_status)}</span>
              </div>
              {selected.analysis.urgency === "emergency" && (
                <div className="call-warning">
                  <AlertTriangle size={18} /> AI urgency is advisory. Confirm immediate danger through the approved emergency procedure.
                </div>
              )}
              <h3>Recommended follow-up</h3>
              <ul className="reasons">
                {selected.analysis.action_items.map((item) => <li key={item}>{item}</li>)}
                {!selected.analysis.action_items.length && <li>Review and route this report manually.</li>}
              </ul>
              <h3>Conversation transcript</h3>
              <div className="transcript">
                {selected.transcript.map((turn, index) => (
                  <div key={`${turn.time_in_call_seconds}-${index}`} className={`turn ${turn.role}`}>
                    <strong>{turn.role === "agent" ? "AI agent" : turn.role === "user" ? "Caller" : "Unknown"}</strong>
                    <p>{turn.message}</p>
                  </div>
                ))}
              </div>
              <div className="review-buttons">
                {(["in_review", "escalated", "resolved"] as CallReviewStatus[]).map((status) => (
                  <button
                    key={status}
                    className={status === "resolved" ? "primary" : "secondary"}
                    disabled={busy || selected.review_status === status}
                    onClick={() => void review(status)}
                  >
                    {status === "resolved" && <CheckCircle2 size={15} />}
                    {humanize(status)}
                  </button>
                ))}
              </div>
            </>
          )}
        </aside>
      </div>
    </section>
  );
}


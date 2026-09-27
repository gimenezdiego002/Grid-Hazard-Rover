import { useEffect, useRef, useState, type FormEvent } from "react";
import { Camera, X, UploadCloud, CheckCircle2 } from "lucide-react";
import { request } from "./api";
import type { UploadResult } from "./contracts";
export default function Upload({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [file, setFile] = useState<File | null>(null),
    [preview, setPreview] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [result, setResult] = useState<UploadResult | null>(null);
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  useEffect(() => {
    if (!file) {
      setPreview("");
      return;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
    setError("");
    setBusy(true);
    setResult(null);
    try {
      if (
        !["image/jpeg", "image/jpg"].includes(file.type) ||
        file.size > 8 * 1024 * 1024
      )
        throw new Error("Choose a JPEG image smaller than 8 MiB.");
      const body = new FormData(event.currentTarget);
      body.set("image", file);
      body.set(
        "timestamp",
        new Date(String(body.get("timestamp"))).toISOString(),
      );
      const response = await request<UploadResult>("/ingest/photo", {
        method: "POST",
        body,
      });
      setResult(response);
      if (response.persisted) onSaved();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Upload failed. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <dialog
      ref={dialog}
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) onClose();
      }}
    >
      <div className="dialog-heading">
        <div>
          <span className="eyebrow">FIELD INTELLIGENCE</span>
          <h2>Turn a photo into evidence.</h2>
        </div>
        <button
          className="icon-button"
          aria-label="Close upload"
          disabled={busy}
          onClick={onClose}
        >
          <X size={20} />
        </button>
      </div>
      <p>
        Gemini evaluates visible hazards. Coordinates and capture time come from
        you—not the image model.
      </p>
      <form onSubmit={submit}>
        <label className="dropzone">
          {preview ? (
            <img src={preview} alt="Selected photograph preview" />
          ) : (
            <>
              <Camera size={34} />
              <strong>Choose a field photograph</strong>
              <span>JPEG · up to 8 MiB / 20 megapixels</span>
            </>
          )}
          <input
            aria-label="JPEG photograph"
            name="image"
            type="file"
            accept="image/jpeg,.jpg,.jpeg"
            required
            disabled={busy}
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setResult(null);
              setError("");
            }}
          />
        </label>
        <div className="form-grid">
          <label>
            Longitude
            <input
              name="longitude"
              type="number"
              step="any"
              min="-180"
              max="180"
              placeholder="-80.36"
              required
            />
          </label>
          <label>
            Latitude
            <input
              name="latitude"
              type="number"
              step="any"
              min="-90"
              max="90"
              placeholder="25.76"
              required
            />
          </label>
          <label>
            Capture time (your local time)
            <input name="timestamp" type="datetime-local" required />
          </label>
          <label>
            Source / operator
            <input
              name="source"
              maxLength={100}
              placeholder="Rover 01 or field survey"
            />
          </label>
        </div>
        <p className="muted">
          Use verified capture coordinates. Internet sample photos must not be
          presented as current field observations.
        </p>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        {result && (
          <div className="upload-result" role="status">
            <CheckCircle2 size={20} />
            <div>
              <strong>
                {result.hazard_detected
                  ? "Hazard classified"
                  : "No hazard detected"}
              </strong>
              <p>{result.classification.description}</p>
              <span>
                {Math.round(result.classification.confidence * 100)}% model
                confidence
                {result.classification.severity !== null
                  ? ` · Severity ${result.classification.severity}/5`
                  : ""}
              </span>
              <p>
                {result.persisted
                  ? "Saved to the active backend repository. Dashboard refreshed."
                  : "No hazard record was saved."}
              </p>
            </div>
          </div>
        )}
        <button
          className="primary wide"
          disabled={busy || !file || !!result}
          type="submit"
        >
          <UploadCloud size={18} />
          {busy
            ? "Analyzing photograph…"
            : result
              ? "Analysis complete"
              : "Analyze with Gemini"}
        </button>
        <small className="muted">
          This sends the photograph to the configured Gemini service. AI output
          requires human review.
        </small>
      </form>
    </dialog>
  );
}

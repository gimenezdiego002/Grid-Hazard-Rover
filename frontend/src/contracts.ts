// JSON representations of shared/schemas.py. Backend validation remains canonical.
import type {
  Point,
  LineString,
  MultiLineString,
  Polygon,
  MultiPolygon,
} from "geojson";
export type Geometry =
  Point | LineString | MultiLineString | Polygon | MultiPolygon;
export type Kind = "project" | "record" | "hazard";
interface Located {
  id: string;
  location: Geometry;
  metadata: { [key: string]: unknown };
}
interface Dated extends Located {
  title: string;
  description: string | null;
  start_date: string | null;
  end_date: string | null;
  status: string | null;
  source_url: string | null;
}
export interface Project extends Dated {
  utility: string;
}
export interface PublicRecord extends Dated {
  source: string;
  record_type: string;
}
export interface Hazard extends Located {
  location: Point;
  hazard_type: string;
  severity: number;
  confidence: number;
  description: string | null;
  timestamp: string;
  image_url: string | null;
}
export interface Match {
  id: string;
  left_id: string;
  left_kind: Kind;
  right_id: string;
  right_kind: Kind;
  distance_m: number;
  distance_tier: "crossing" | "under_1_6km" | "under_8km" | "under_40km";
  intersects: boolean;
  timeline_overlap: boolean | null;
  timeline_gap_days: number | null;
  closest_points: [[number, number], [number, number]] | null;
  metadata: { [key: string]: unknown };
}
export interface RiskCell extends Located {
  location: Polygon;
  score: number;
  level: "LOW" | "MODERATE" | "HIGH" | "CRITICAL";
  components: { [key: string]: number };
  reasons: string[];
  project_ids: string[];
  record_ids: string[];
  hazard_ids: string[];
  match_ids: string[];
}
export interface Snapshot {
  projects: Project[];
  records: PublicRecord[];
  hazards: Hazard[];
  matches: Match[];
  risk_cells: RiskCell[];
}
export interface UploadResult {
  hazard_detected: boolean;
  classification: {
    hazard_type: string | null;
    severity: number | null;
    confidence: number;
    description: string;
  };
  hazard: Hazard | null;
  persisted: boolean;
}
export type Selection = { kind: Kind | "risk" | "match"; id: string };
export const fixture = (item: Located) =>
  item.metadata.is_fixture === true || item.metadata.demo === true;
export const humanize = (value: string) => value.replaceAll("_", " ");
export const distance = (meters: number) =>
  meters === 0
    ? "Crossing"
    : meters < 1000
      ? `${Math.round(meters)} m`
      : `${(meters / 1000).toFixed(1)} km`;
export const timeline = (m: Match) =>
  m.timeline_overlap === null
    ? "Schedule unknown"
    : m.timeline_overlap
      ? "Schedules overlap"
      : m.timeline_gap_days !== null
        ? `${m.timeline_gap_days} days apart`
        : "No overlap";

import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import type { Selection, Snapshot } from "./contracts";

export const colors = {
  project: "#087f8c",
  record: "#5558a8",
  hazard: "#b84800",
  risk: "#b82020",
  match: "#0a2e3f",
};

const utilityPalette = ["#087f8c", "#5558a8", "#b84800", "#5c9470", "#c97b00"];
const riskColors = {
  LOW: "#5c9470",
  MODERATE: "#c97b00",
  HIGH: "#b84800",
  CRITICAL: "#b82020",
} as const;
const hazardSymbol: Record<string, string> = {
  pothole: "◉",
  flooding: "≈",
  standing_water: "≈",
  water: "≈",
  vegetation: "♧",
  leaning_pole: "⚡",
  damaged_pole: "⚡",
  exposed_cable: "⚡",
  debris_or_obstruction: "!",
  debris: "!",
};
const statusStyle: Record<string, { label: string; background: string; color: string }> = {
  active: { label: "Active", background: "#fef3c7", color: "#8a5100" },
  "in-review": { label: "In review", background: "#eaeaf8", color: "#363879" },
  planning: { label: "Planning", background: "#eef2f7", color: "#4d7089" },
  completed: { label: "Completed", background: "#d4ebdc", color: "#2e6b42" },
  unknown: { label: "Status unknown", background: "#eef2f7", color: "#4d7089" },
};
const kindLabel = {
  project: "Utility projects",
  record: "Public works",
  hazard: "Rover hazards",
  risk: "Risk areas",
} as const;

function utilityColor(utility: string) {
  let hash = 0;
  for (const character of utility) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  return utilityPalette[hash % utilityPalette.length];
}

function escapeHtml(value: string) {
  return value.replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;",
  })[character]!);
}

function normalizedStatus(status: string | null) {
  const key = (status || "unknown").trim().toLowerCase().replaceAll("_", "-");
  return statusStyle[key] ?? {
    label: status || "Status unknown",
    background: "#eef2f7",
    color: "#4d7089",
  };
}

interface MapNotice {
  kind: "hazard" | "risk";
  id: string;
  point: L.LatLng;
  label: string;
  detail: string;
  color: string;
  symbol: string;
  active: boolean;
  severity?: number;
  score?: number;
  level?: string;
}

function clusterNotices(notices: MapNotice[], thresholdMeters = 140) {
  const clusters: MapNotice[][] = [];
  for (const notice of notices) {
    const cluster = clusters.find((candidate) =>
      candidate.some((member) => member.point.distanceTo(notice.point) <= thresholdMeters),
    );
    if (cluster) cluster.push(notice);
    else clusters.push([notice]);
  }
  return clusters;
}

function noticeList(
  notices: MapNotice[],
  interactive: boolean,
  onSelect: (selection: Selection) => void,
) {
  const root = document.createElement("div");
  root.className = "map-cluster-list";
  const heading = document.createElement("strong");
  heading.textContent = `${notices.length} nearby map items`;
  const hint = document.createElement("small");
  hint.textContent = interactive ? "Choose an item to inspect" : "Click the marker to choose one";
  root.append(heading, hint);
  for (const notice of notices) {
    const row = document.createElement(interactive ? "button" : "div");
    row.className = "map-cluster-row";
    if (row instanceof HTMLButtonElement) {
      row.type = "button";
      row.addEventListener("click", () => onSelect({ kind: notice.kind, id: notice.id }));
    }
    const dot = document.createElement("i");
    dot.style.background = notice.color;
    dot.textContent = notice.symbol;
    const copy = document.createElement("span");
    const title = document.createElement("b");
    title.textContent = notice.label;
    const detail = document.createElement("small");
    detail.textContent = notice.detail;
    copy.append(title, detail);
    row.append(dot, copy);
    root.append(row);
  }
  return root;
}

export default function MapView({
  data,
  selected,
  onSelect,
}: {
  data: Snapshot;
  selected: Selection | null;
  onSelect: (selection: Selection) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const fitted = useRef(false);
  const [layers, setLayers] = useState({
    project: true,
    record: true,
    hazard: true,
    risk: true,
  });
  const [tilesFailed, setTilesFailed] = useState(false);

  useEffect(() => {
    const instance = L.map(host.current!, {
      zoomControl: false,
      zoomAnimation: false,
      fadeAnimation: false,
      markerZoomAnimation: false,
    }).setView([25.76, -80.25], 11);
    map.current = instance;
    L.control.zoom({ position: "bottomright" }).addTo(instance);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    })
      .on("tileerror", () => setTilesFailed(true))
      .addTo(instance);
    const observer = new ResizeObserver(() => instance.invalidateSize());
    observer.observe(host.current!);
    return () => {
      observer.disconnect();
      instance.stop();
      instance.remove();
      map.current = null;
      fitted.current = false;
    };
  }, []);

  useEffect(() => {
    const instance = map.current!;
    const group = L.featureGroup().addTo(instance);
    const allBounds = L.latLngBounds([]);
    const notices: MapNotice[] = [];
    let selectedBounds: L.LatLngBounds | undefined;
    const entries = [
      ...data.risk_cells.map((item) => ({ item, kind: "risk" as const })),
      ...data.records.map((item) => ({ item, kind: "record" as const })),
      ...data.projects.map((item) => ({ item, kind: "project" as const })),
      ...data.hazards.map((item) => ({ item, kind: "hazard" as const })),
    ];

    for (const { item, kind } of entries) {
      const active = selected?.kind === kind && selected.id === item.id;
      const isRisk = kind === "risk";
      const isProject = kind === "project";
      const isRecord = kind === "record";
      const visible = layers[kind] || active;
      const hazardSeverity = "severity" in item ? item.severity : 0;
      const hazardType = "hazard_type" in item ? item.hazard_type : "hazard";
      const projectColor = isProject && "utility" in item ? utilityColor(item.utility) : colors.project;
      const riskColor = isRisk && "level" in item ? riskColors[item.level] : colors.risk;
      const projectStatus = isProject && "status" in item ? normalizedStatus(item.status) : normalizedStatus(null);

      if (isRisk && visible) {
        L.geoJSON(item.location, {
          style: {
            color: riskColor,
            weight: active ? 24 : 20,
            opacity: active ? 0.1 : 0.065,
            fillColor: riskColor,
            fillOpacity: 0.035,
            lineCap: "round",
            lineJoin: "round",
          },
          interactive: false,
        }).addTo(group);
        L.geoJSON(item.location, {
          style: {
            color: riskColor,
            weight: active ? 12 : 9,
            opacity: active ? 0.16 : 0.1,
            fillColor: riskColor,
            fillOpacity: 0.07,
            lineCap: "round",
            lineJoin: "round",
          },
          interactive: false,
        }).addTo(group);
      }

      if (isProject && visible) {
        L.geoJSON(item.location, {
          style: {
            color: projectColor,
            weight: active ? 22 : 17,
            opacity: active ? 0.2 : 0.12,
            fillColor: projectColor,
            fillOpacity: active ? 0.17 : 0.1,
            lineCap: "round",
            lineJoin: "round",
          },
          interactive: false,
        }).addTo(group);
      }

      const feature = L.geoJSON(item.location, {
        style: {
          color: isRisk ? riskColor : isProject ? projectColor : colors[kind],
          weight: active ? 5 : isRisk ? 2 : isProject ? 3.2 : isRecord ? 5 : 2.5,
          opacity: isRecord ? 0.52 : isRisk ? 0.65 : 0.88,
          dashArray: isRecord ? "12 8" : isProject && projectStatus.label !== "Active" ? "10 6" : undefined,
          fillColor: isRisk ? riskColor : isProject ? projectColor : colors[kind],
          fillOpacity: isRisk
            ? Math.min(0.24, 0.07 + ("score" in item ? item.score / 650 : 0))
            : isProject
              ? 0.1
              : 0.16,
          lineCap: "round",
          lineJoin: "round",
        },
        pointToLayer: (_, latlng) =>
          L.circleMarker(latlng, {
            radius: active ? 11 : isRisk ? 7 : 8,
            color: active ? "#0a2e3f" : isRisk ? riskColor : "white",
            weight: active ? 3 : 2,
            fillColor: isRisk ? riskColor : colors[kind],
            fillOpacity: 1,
          }),
      });

      const title =
        "title" in item
          ? item.title
          : "hazard_type" in item
            ? item.hazard_type.replaceAll("_", " ")
            : `Risk index ${item.score}/100`;
      const tooltip = document.createElement(isProject ? "div" : "span");
      if (isProject && "utility" in item) {
        tooltip.className = "corridor-label";
        tooltip.style.setProperty("--corridor-color", projectColor);
        const projectName = document.createElement("div");
        projectName.className = "cl-name";
        projectName.textContent = item.title;
        const utility = document.createElement("div");
        utility.className = "cl-company";
        utility.textContent = item.utility;
        const status = document.createElement("span");
        status.className = "cl-badge";
        status.style.background = projectStatus.background;
        status.style.color = projectStatus.color;
        status.textContent = projectStatus.label;
        tooltip.append(projectName, utility, status);
      } else {
        tooltip.textContent = isRisk
          ? `${item.score}/100 · ${item.level}`
          : isHazard(item)
            ? `${hazardType.replaceAll("_", " ")} · ${hazardSeverity}/5`
            : title;
      }
      feature
        .bindTooltip(tooltip, {
          direction: isRisk ? "center" : "top",
          sticky: isProject,
          offset: isProject ? [0, -10] : undefined,
          className: isRisk
            ? "risk-tooltip"
            : isProject
              ? "project-card-tooltip"
              : "map-feature-tooltip",
        })
        .on("click", () => onSelect({ kind, id: item.id }));
      allBounds.extend(feature.getBounds());
      if (visible) feature.addTo(group);

      if (isHazard(item) && (layers.hazard || active)) {
        const hazardLabel = hazardType.replaceAll("_", " ");
        notices.push({
          kind: "hazard",
          id: item.id,
          point: feature.getBounds().getCenter(),
          label: hazardLabel,
          detail: `Severity ${hazardSeverity}/5`,
          color: hazardSeverity >= 4 ? "#c63f3f" : hazardSeverity >= 3 ? "#e77934" : "#ddb13a",
          symbol: hazardSymbol[hazardType] ?? "!",
          active,
          severity: hazardSeverity,
        });
      }

      if (isRisk && (layers.risk || active)) {
        const score = "score" in item ? item.score : 0;
        const level = "level" in item ? item.level : "RISK";
        notices.push({
          kind: "risk",
          id: item.id,
          point: feature.getBounds().getCenter(),
          label: `${String(level).toLowerCase()} risk area`,
          detail: `${score.toFixed(0)}/100 Coordination Risk Index`,
          color: riskColor,
          symbol: score.toFixed(0),
          active,
          score,
          level: String(level),
        });
      }

      if (active) selectedBounds = feature.getBounds();
    }

    for (const cluster of clusterNotices(notices)) {
      if (cluster.length === 1) {
        const notice = cluster[0];
        if (notice.kind === "hazard") {
          const severity = notice.severity ?? 1;
          const size = severity >= 5 ? 40 : severity >= 4 ? 36 : severity >= 3 ? 32 : 29;
          L.marker(notice.point, {
            icon: L.divIcon({
              className: `hazard-icon-wrap haz-pin${notice.active ? " selected" : ""}`,
              html: `<span class="hazard-icon severity-${severity}" style="width:${size}px;height:${size}px">${escapeHtml(notice.symbol)}</span><small>${escapeHtml(notice.label)}</small>`,
              iconSize: [116, size + 23],
              iconAnchor: [58, Math.round(size / 2)],
            }),
            keyboard: false,
            zIndexOffset: severity >= 4 ? 900 : 600,
          })
            .addTo(group)
            .on("click", () => onSelect({ kind: notice.kind, id: notice.id }));
        } else {
          const level = (notice.level ?? "RISK").toLowerCase();
          L.marker(notice.point, {
            icon: L.divIcon({
              className: "risk-score-wrap",
              html: `<span class="risk-score-label risk-${escapeHtml(level)}${notice.active ? " selected" : ""}"><i></i><strong>${notice.score?.toFixed(0) ?? "–"}</strong><small>${escapeHtml(level)} risk</small></span>`,
              iconSize: [126, 34],
              iconAnchor: [63, 17],
            }),
            keyboard: false,
            zIndexOffset: 500,
          })
            .addTo(group)
            .on("click", () => onSelect({ kind: notice.kind, id: notice.id }));
        }
        continue;
      }

      const center = L.latLng(
        cluster.reduce((sum, notice) => sum + notice.point.lat, 0) / cluster.length,
        cluster.reduce((sum, notice) => sum + notice.point.lng, 0) / cluster.length,
      );
      const containsActive = cluster.some((notice) => notice.active);
      const marker = L.marker(center, {
        icon: L.divIcon({
          className: "map-notice-cluster-wrap",
          html: `<span class="map-notice-cluster${containsActive ? " selected" : ""}"><strong>${cluster.length}</strong><small>nearby</small></span>`,
          iconSize: [54, 54],
          iconAnchor: [27, 27],
        }),
        keyboard: true,
        title: `${cluster.length} nearby map items`,
        zIndexOffset: 1100,
      }).addTo(group);
      marker.bindTooltip(noticeList(cluster, false, onSelect), {
        direction: "top",
        offset: [0, -22],
        className: "cluster-list-tooltip",
      });
      marker.bindPopup(noticeList(cluster, true, onSelect), {
        className: "cluster-list-popup",
        offset: [0, -18],
        minWidth: 250,
      });
    }

    const match =
      selected?.kind === "match"
        ? data.matches.find((candidate) => candidate.id === selected.id)
        : undefined;
    if (match?.closest_points) {
      const line = L.polyline(
        match.closest_points.map(([longitude, latitude]) => [latitude, longitude]),
        { color: colors.match, weight: 4, dashArray: "7 7" },
      ).addTo(group);
      line.bindTooltip(`${Math.round(match.distance_m)} m · closest points`, {
        sticky: true,
        className: "match-tooltip",
      });
      match.closest_points.forEach(([longitude, latitude]) =>
        L.circleMarker([latitude, longitude], {
          radius: 7,
          color: colors.match,
        }).addTo(group),
      );
      selectedBounds = line.getBounds();
    }

    if (selectedBounds?.isValid()) {
      instance.fitBounds(selectedBounds, {
        padding: [65, 65],
        maxZoom: 15,
        animate: false,
      });
    } else if (!fitted.current && allBounds.isValid()) {
      const priority = [...data.risk_cells].sort((a, b) => b.score - a.score)[0];
      const bounds = priority ? L.geoJSON(priority.location).getBounds() : allBounds;
      instance.fitBounds(bounds, {
        padding: [45, 45],
        maxZoom: 14,
        animate: false,
      });
      fitted.current = true;
    }

    return () => {
      group.remove();
    };
  }, [data, selected, layers, onSelect]);

  return (
    <section className="map-wrap" aria-label="Interactive coordination map">
      <div ref={host} className="map" />
      <div className="map-caption">
        <span className="live-dot" /> MIAMI-DADE COUNTY
        <small>V2 coordination intelligence · select a feature for evidence</small>
      </div>
      <div className="map-layers">
        {(Object.keys(layers) as (keyof typeof layers)[]).map((kind) => (
          <label key={kind}>
            <input
              type="checkbox"
              checked={layers[kind]}
              onChange={() => setLayers({ ...layers, [kind]: !layers[kind] })}
            />
            <i style={{ background: colors[kind] }} />
            {kindLabel[kind]}
          </label>
        ))}
      </div>
      {tilesFailed && (
        <div className="tile-warning">
          Basemap tiles unavailable. Project overlays remain available.
        </div>
      )}
    </section>
  );
}

function isHazard(
  item:
    | Snapshot["hazards"][number]
    | Snapshot["projects"][number]
    | Snapshot["records"][number]
    | Snapshot["risk_cells"][number],
): item is Snapshot["hazards"][number] {
  return "hazard_type" in item;
}

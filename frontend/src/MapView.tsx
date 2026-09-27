import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import type { Selection, Snapshot } from "./contracts";
export const colors = {
  project: "#087f8c",
  record: "#7865b7",
  hazard: "#e77934",
  risk: "#e15b51",
  match: "#112d32",
};
export default function MapView({
  data,
  selected,
  onSelect,
}: {
  data: Snapshot;
  selected: Selection | null;
  onSelect: (s: Selection) => void;
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
    let selectedBounds: L.LatLngBounds | undefined;
    const entries = [
      ...data.risk_cells.map((item) => ({ item, kind: "risk" as const })),
      ...data.records.map((item) => ({ item, kind: "record" as const })),
      ...data.projects.map((item) => ({ item, kind: "project" as const })),
      ...data.hazards.map((item) => ({ item, kind: "hazard" as const })),
    ];
    for (const { item, kind } of entries) {
      const active = selected?.kind === kind && selected.id === item.id;
      const feature = L.geoJSON(item.location, {
        style: {
          color: colors[kind],
          weight: active ? 5 : kind === "risk" ? 1.5 : 3,
          fillOpacity: kind === "risk" ? 0.12 : 0.18,
        },
        pointToLayer: (_, latlng) =>
          L.circleMarker(latlng, {
            radius: active ? 10 : 6,
            color: active ? "#112d32" : "white",
            weight: 2,
            fillColor: colors[kind],
            fillOpacity: 1,
          }),
      });
      const title =
        "title" in item
          ? item.title
          : "hazard_type" in item
            ? item.hazard_type.replaceAll("_", " ")
            : `Risk index ${item.score}/100`;
      const label = document.createElement("span");
      label.textContent = title;
      feature
        .bindTooltip(label)
        .on("click", () => onSelect({ kind, id: item.id }));
      allBounds.extend(feature.getBounds());
      if (layers[kind] || active) feature.addTo(group);
      if (active) selectedBounds = feature.getBounds();
    }
    const match =
      selected?.kind === "match"
        ? data.matches.find((m) => m.id === selected.id)
        : undefined;
    if (match?.closest_points) {
      const line = L.polyline(
        match.closest_points.map(([lng, lat]) => [lat, lng]),
        { color: colors.match, weight: 4, dashArray: "7 7" },
      ).addTo(group);
      match.closest_points.forEach(([lng, lat]) =>
        L.circleMarker([lat, lng], { radius: 7, color: colors.match }).addTo(
          group,
        ),
      );
      selectedBounds = line.getBounds();
    }
    if (selectedBounds?.isValid())
      instance.fitBounds(selectedBounds, {
        padding: [65, 65],
        maxZoom: 15,
        animate: false,
      });
    else if (!fitted.current && allBounds.isValid()) {
      const priority = [...data.risk_cells].sort(
        (a, b) => b.score - a.score,
      )[0];
      const bounds = priority
        ? L.geoJSON(priority.location).getBounds()
        : allBounds;
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
        <span className="live-dot" /> MIAMI-DADE COUNTY{" "}
        <small>Infrastructure intelligence</small>
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
            {kind === "risk"
              ? "Risk areas"
              : `${kind[0].toUpperCase()}${kind.slice(1)}s`}
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

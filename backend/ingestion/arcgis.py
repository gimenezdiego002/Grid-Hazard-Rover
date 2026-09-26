"""Bounded read-only ArcGIS requests and verifiable object-ID batch fetching."""

from datetime import datetime, timezone
import time

import httpx

from .sources import Source


class SourceError(ValueError):
    """A source could not produce a verifiable snapshot."""


class ArcGIS:
    def __init__(self, client: httpx.Client, *, retries: int = 2):
        self.client = client
        self.retries = retries

    def get(self, url: str, **params) -> dict:
        for attempt in range(self.retries + 1):
            try:
                response = self.client.get(url, params=params)
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < self.retries:
                        time.sleep(0.5 * (2 ** attempt))
                        continue
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict):
                    raise SourceError("Expected a JSON object")
                if "error" in body:
                    error = body["error"]
                    raise SourceError(f"ArcGIS error: {error}")
                return body
            except httpx.TransportError as exc:
                if attempt == self.retries:
                    raise SourceError(f"Network request failed: {type(exc).__name__}") from exc
                time.sleep(0.5 * (2 ** attempt))
            except (httpx.HTTPStatusError, ValueError) as exc:
                raise SourceError(str(exc)) from exc
        raise SourceError("Request retries exhausted")

    def inspect(self, source: Source) -> dict:
        metadata = self.get(source.url, f="json")
        fields = {field["name"]: field for field in metadata.get("fields", [])}
        missing = set(source.fields) - fields.keys()
        if missing:
            raise SourceError(f"Source schema changed; missing fields: {sorted(missing)}")
        oid = metadata.get("objectIdField") or next(
            (key for key, field in fields.items() if field.get("type") == "esriFieldTypeOID"), None
        )
        if not oid:
            raise SourceError("Source has no object-ID field")
        if "geojson" not in metadata.get("supportedQueryFormats", "").lower():
            raise SourceError("Source does not advertise GeoJSON")
        result = self.get(source.url + "/query", f="json", where=source.where,
                          returnCountOnly="true")
        count = result.get("count")
        if type(count) is not int or count < 0:
            raise SourceError("Invalid source record count")
        return {
            "source": source.name, "source_url": source.url, "where": source.where,
            "reference_date": source.reference_date,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "total_count": count, "object_id_field": oid,
            "max_record_count": metadata.get("maxRecordCount", 1000),
            "fields": list(fields), "geometry_type": metadata.get("geometryType"),
            "time_reference": metadata.get("dateFieldsTimeReference") or metadata.get("timeInfo"),
        }

    def fetch(self, source: Source, *, limit: int = 100) -> dict:
        if limit < 0:
            raise ValueError("limit must be nonnegative; 0 requests all matching rows")
        info = self.inspect(source)
        query = source.url + "/query"
        result = self.get(query, f="json", where=source.where, returnIdsOnly="true")
        ids = result.get("objectIds")
        if ids is None and info["total_count"] == 0:
            ids = []
        if not isinstance(ids, list) or any(type(oid) is not int for oid in ids):
            raise SourceError("Invalid object-ID list")
        if len(set(ids)) != len(ids) or len(ids) != info["total_count"]:
            raise SourceError("Count/ID mismatch; source may have changed, retry the fetch")
        selected = sorted(ids)[:limit] if limit else sorted(ids)
        if len(selected) > 10000:
            raise SourceError("More than 10,000 rows requested; narrow the source selection")
        batch_size = min(100, int(info["max_record_count"]))
        if batch_size < 1:
            raise SourceError("Invalid source response limit")
        oid_field = info["object_id_field"]
        features = []
        for offset in range(0, len(selected), batch_size):
            batch = selected[offset:offset + batch_size]
            page = self.get(
                query, f="geojson", objectIds=",".join(map(str, batch)),
                outFields=",".join(dict.fromkeys((oid_field,) + source.fields)),
                returnGeometry="true", outSR=4326, returnZ="false", returnM="false",
            )
            rows = page.get("features")
            if page.get("type") != "FeatureCollection" or not isinstance(rows, list):
                raise SourceError("Expected a GeoJSON FeatureCollection")
            if any(not isinstance(row, dict) or not isinstance(row.get("properties"), dict) for row in rows):
                raise SourceError("Malformed feature in GeoJSON response")
            actual = [row["properties"].get(oid_field) for row in rows]
            if any(type(oid) is not int for oid in actual):
                raise SourceError("Missing or invalid object ID in GeoJSON response")
            if len(actual) != len(batch) or set(actual) != set(batch):
                raise SourceError("Incomplete or duplicate object-ID batch; snapshot not exported")
            features.extend(rows)
        features.sort(key=lambda row: row["properties"][oid_field])
        info.update({
            "schema_version": 1, "is_fixture": False, "selected_count": len(selected),
            "selection": "all" if len(selected) == len(ids) else "sample",
            "complete_for_selection": True, "features": features,
        })
        return info

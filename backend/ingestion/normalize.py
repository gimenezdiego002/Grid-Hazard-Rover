"""Source-specific mappings into the existing shared models."""

from datetime import date, datetime, timezone
import hashlib
import json

from shapely.geometry import shape
from shapely.validation import explain_validity

from shared.schemas import Project, Record
from .sources import SOURCES


def text(value) -> str | None:
    if value is None:
        return None
    return str(value).strip() or None


def arcgis_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("Boolean is not a date")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, timezone.utc).date()
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


def normalize_feature(feature: dict, snapshot: dict) -> Project | Record:
    source = snapshot["source"]
    p = feature["properties"]
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict):
        raise ValueError("Missing GeoJSON geometry")
    oid = text(p.get(snapshot["object_id_field"]))
    if not oid:
        raise ValueError("Missing source object ID")
    metadata = {
        "source": source, "source_object_id": oid,
        "fetched_at": snapshot["fetched_at"],
        "is_fixture": snapshot.get("is_fixture", False),
        "geometry_precision": "source_geometry_unverified_accuracy",
        "date_precision": "source_day_fields",
        "source_time_reference": snapshot.get("time_reference"),
        "date_conversion": "Numeric ArcGIS timestamps interpreted as UTC epoch milliseconds; source date precision preserved",
    }
    # Namespace + GlobalID is durable when supplied. OID fallback identifies
    # source features/segments but may change if the publisher rebuilds a layer.
    global_id = text(p.get("GlobalID"))
    identity = global_id or oid
    metadata["identity_basis"] = "GlobalID" if global_id else "OBJECTID"
    metadata["identity_caveat"] = None if global_id else "May change on source republish"
    common = {
        "id": f"{source}:{identity}", "location": geometry,
        "source_url": SOURCES[source].url, "metadata": metadata,
    }
    if source == "imdc_power":
        utility = text(p.get("AGCYNAME"))
        if not utility:
            raise ValueError("Missing utility/operator identity (AGCYNAME)")
        metadata.update({"source_project_id": text(p.get("PROJECTID")),
                         "utility_type": text(p.get("FACTYPE"))})
        entity = Project(
            **common, utility=utility,
            title=text(p.get("PRJNAME")) or f"Power project {text(p.get('PROJECTID')) or identity}",
            description=text(p.get("PRJSCOPE")),
            status=text(p.get("GENPRJSTAT")) or text(p.get("AGYPRJSTAT")),
            start_date=arcgis_date(p.get("STARTDATE")), end_date=arcgis_date(p.get("ENDDATE")),
        )
    elif source == "fdot_work_program":
        metadata.update({"fiscal_year": p.get("FISCALYR"), "date_precision": "fiscal_year",
                         "source_project_id": text(p.get("FINPROJ")),
                         "financial_sequence": text(p.get("FINPRJSQ")),
                         "roadway_id": text(p.get("RDWYID")),
                         "begin_section": p.get("BEGSECPT"), "end_section": p.get("ENDSECPT")})
        entity = Record(
            **common, source="FDOT", record_type="planned_road_construction",
            title=text(p.get("LOCALFULL")) or f"FDOT project {text(p.get('FINPROJ')) or identity}",
            status=text(p.get("WPITSTNM")),
        )
    elif source == "fdot_active":
        metadata.update({"source_project_id": text(p.get("FinProjNum")),
                         "contract_id": text(p.get("ContractId")), "item": text(p.get("Item")),
                         "segment": text(p.get("ItemSeg")), "end_date_estimated": True,
                         "warranty_flag": text(p.get("is820days"))})
        entity = Record(
            **common, source="FDOT", record_type="active_road_construction",
            title=text(p.get("Description")) or f"FDOT contract {text(p.get('ContractId')) or identity}",
            status="warranty" if p.get("is820days") == "Y" else "active" if p.get("is820days") == "N" else None,
            start_date=arcgis_date(p.get("StartDate")), end_date=arcgis_date(p.get("EstEndDate")),
        )
    else:
        raise ValueError(f"Unsupported source: {source}")
    geom = shape(entity.location.model_dump(mode="json"))
    if geom.is_empty or not geom.is_valid:
        raise ValueError(f"Invalid geometry topology: {explain_validity(geom)}")
    # No geometry repairs or inferred construction dates occur here.
    return entity


def normalize_snapshot(snapshot: dict) -> dict:
    if snapshot.get("source") not in SOURCES:
        raise ValueError("Unknown source")
    features = snapshot.get("features")
    if not isinstance(features, list):
        raise ValueError("Snapshot must contain a features array")
    if snapshot.get("complete_for_selection") is not True or len(features) != snapshot.get("selected_count"):
        raise ValueError("Incomplete snapshot cannot be exported")
    if not snapshot.get("fetched_at") or not snapshot.get("object_id_field"):
        raise ValueError("Snapshot provenance is missing")
    total = snapshot.get("total_count")
    if type(total) is not int or total < len(features):
        raise ValueError("Invalid snapshot total_count")
    if snapshot.get("selection") not in ("sample", "all"):
        raise ValueError("Snapshot must declare sample/all selection")
    if snapshot["selection"] == "all" and total != len(features):
        raise ValueError("Complete snapshot count mismatch")
    datetime.fromisoformat(snapshot["fetched_at"].replace("Z", "+00:00"))
    projects, records, rejected = [], [], []
    seen = {}
    duplicates = 0
    for index, feature in enumerate(features):
        try:
            entity = normalize_feature(feature, snapshot)
            payload = entity.model_dump(mode="json")
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError, OSError) as exc:
            rejected.append({"source": snapshot["source"], "feature_index": index,
                             "source_object_id": feature.get("properties", {}).get(snapshot["object_id_field"]) if isinstance(feature, dict) and isinstance(feature.get("properties"), dict) else None,
                             "reason": str(exc)})
            continue
        # A conflicting identity makes the snapshot ambiguous: do not pick the
        # first row and hand it to the database as if it were authoritative.
        if entity.id in seen:
            if seen[entity.id] != payload:
                raise ValueError(f"Conflicting duplicate identity: {entity.id}")
            duplicates += 1
            continue
        seen[entity.id] = payload
        (projects if isinstance(entity, Project) else records).append(payload)
    canonical_bytes = json.dumps(snapshot, sort_keys=True, allow_nan=False).encode()
    manifest = {key: value for key, value in snapshot.items() if key != "features"}
    manifest.update({
        "snapshot_sha256": hashlib.sha256(canonical_bytes).hexdigest(),
        "accepted": len(projects) + len(records), "duplicates": duplicates,
        "rejected": len(rejected), "quality": "has_rejections" if rejected else "valid",
        "utility_operators": sorted({p["utility"] for p in projects}),
        "limitations": [
            "Source rows are not guaranteed future; inspect status and dates before matching.",
            "This export does not establish two distinct electric utilities' future plans.",
            "OBJECTID-based identities may change when a source is republished.",
        ],
    })
    return {"projects": sorted(projects, key=lambda p: p["id"]),
            "records": sorted(records, key=lambda r: r["id"]),
            "rejected": rejected, "manifest": manifest}

"""Offline verification: python -m unittest backend.ingestion.test_ingestion -v."""

from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import httpx

from shared.schemas import Project, Record
from .arcgis import ArcGIS, SourceError
from .normalize import arcgis_date, normalize_snapshot
from .sources import SOURCES, source_for
from .__main__ import main


FIXTURE = Path(__file__).resolve().parents[2] / "shared/fixtures/ingestion/imdc_power.snapshot.json"


def fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def fdot_snapshot(source="fdot_work_program"):
    data = fixture()
    data.update(source=source, source_url=SOURCES[source].url, total_count=1, selected_count=1)
    data["features"] = [{"type": "Feature", "properties": {
        "OBJECTID": 12, "FINPROJ": "123456", "FINPRJSQ": "01", "FISCALYR": 2027,
        "LOCALFULL": "Synthetic resurfacing", "WPITSTNM": "Planned", "RDWYID": "0001",
        "BEGSECPT": 0, "ENDSECPT": 2,
        "ContractId": "DEMO123", "Item": "123456", "ItemSeg": "01",
        "Description": "Synthetic active work", "is820days": "N",
        "StartDate": 1798761600000, "EstEndDate": "2027-06-30T00:00:00Z",
    }, "geometry": {"type": "LineString", "coordinates": [[-80.36,25.76],[-80.35,25.77]]}}]
    return data


class NormalizeTests(unittest.TestCase):
    def test_project_roundtrip_and_determinism(self):
        result = normalize_snapshot(fixture())
        self.assertEqual(result, normalize_snapshot(fixture()))
        self.assertEqual(result["manifest"]["accepted"], 3)
        self.assertEqual(result["manifest"]["utility_operators"], ["Demo Electric A", "Demo Electric B"])
        for row in result["projects"]:
            self.assertEqual(Project.model_validate(row).model_dump(mode="json"), row)
            self.assertTrue(row["metadata"]["is_fixture"])

    def test_unknown_dates_stay_unknown(self):
        row = normalize_snapshot(fixture())["projects"][-1]
        self.assertIsNone(row["start_date"])
        self.assertIsNone(row["end_date"])

    def test_fiscal_year_is_not_construction_schedule(self):
        row = normalize_snapshot(fdot_snapshot())["records"][0]
        Record.model_validate(row)
        self.assertIsNone(row["start_date"])
        self.assertIsNone(row["end_date"])
        self.assertEqual(row["metadata"]["fiscal_year"], 2027)

    def test_active_dates_and_estimate(self):
        row = normalize_snapshot(fdot_snapshot("fdot_active"))["records"][0]
        self.assertEqual(row["start_date"], "2027-01-01")
        self.assertEqual(row["end_date"], "2027-06-30")
        self.assertTrue(row["metadata"]["end_date_estimated"])

    def test_segments_do_not_overwrite(self):
        data = fdot_snapshot()
        second = deepcopy(data["features"][0])
        second["properties"].update(OBJECTID=13, BEGSECPT=2, ENDSECPT=3)
        data["features"].append(second)
        data.update(total_count=2, selected_count=2)
        self.assertEqual(len(normalize_snapshot(data)["records"]), 2)

    def test_identical_duplicate_counted(self):
        data = fixture()
        data["features"].append(deepcopy(data["features"][0]))
        data.update(total_count=4, selected_count=4)
        result = normalize_snapshot(data)
        self.assertEqual(result["manifest"]["duplicates"], 1)
        self.assertEqual(result["manifest"]["accepted"], 3)

    def test_conflicting_duplicate_is_reported(self):
        data = fixture()
        row = deepcopy(data["features"][0])
        row["properties"]["PRJNAME"] = "Conflicting title"
        data["features"].append(row)
        data.update(total_count=4, selected_count=4)
        with self.assertRaisesRegex(ValueError, "Conflicting duplicate"):
            normalize_snapshot(data)

    def test_invalid_inputs_are_quarantined(self):
        mutations = [
            lambda row: row.update(geometry=None),
            lambda row: row.update(geometry={"type":"LineString", "coordinates":[]}),
            lambda row: row["properties"].update(AGCYNAME=" "),
            lambda row: row["properties"].update(ENDDATE="2020-01-01"),
            lambda row: row["properties"].update(STARTDATE="not a date"),
            lambda row: row.update(geometry={"type":"Point", "coordinates":[181,25]}),
            lambda row: row.update(geometry={"type":"Polygon", "coordinates":[[
                [-80.36,25.76],[-80.35,25.77],[-80.36,25.77],[-80.35,25.76],[-80.36,25.76]]]}),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                data = fixture()
                mutate(data["features"][0])
                result = normalize_snapshot(data)
                self.assertEqual(result["manifest"]["rejected"], 1)
                self.assertEqual(result["manifest"]["accepted"], 2)

    def test_incomplete_snapshot_rejected(self):
        data = fixture()
        data["complete_for_selection"] = False
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            normalize_snapshot(data)

    def test_date_formats(self):
        self.assertIsNone(arcgis_date(None))
        self.assertEqual(arcgis_date(0), date(1970,1,1))
        self.assertEqual(arcgis_date("2027-01-01"), date(2027,1,1))
        with self.assertRaises(ValueError):
            arcgis_date(True)

    def test_cli_writes_roundtrippable_files_and_refuses_overwrite(self):
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "export"
            args = ["ingestion", "normalize", str(FIXTURE), "--output", str(output)]
            with patch("sys.argv", args), patch("builtins.print"):
                self.assertEqual(main(), 0)
                self.assertEqual(main(), 1)
            rows = json.loads((output / "projects.json").read_text(encoding="utf-8"))
            self.assertEqual(len(rows), 3)
            for row in rows:
                Project.model_validate(row)


class ArcGISTests(unittest.TestCase):
    def test_work_program_reference_year_filter(self):
        source = source_for("fdot_work_program", date(2026,9,26))
        self.assertIn("FISCALYR >= 2026", source.where)
        self.assertEqual(source.reference_date, "2026-09-26")

    def client(self, *, count=3, missing_row=False, bad_ids=False, error=False):
        self.queries = []
        source = SOURCES["imdc_power"]
        def handle(request):
            q = request.url.params
            self.queries.append(dict(q))
            if error:
                return httpx.Response(200, json={"error": {"code": 400, "message": "Bad query"}})
            if request.url.path.endswith("/9"):
                return httpx.Response(200, json={
                    "fields": [{"name": name, "type": "esriFieldTypeString"} for name in source.fields]
                              + [{"name": "OBJECTID", "type": "esriFieldTypeOID"}],
                    "supportedQueryFormats": "JSON, geoJSON", "maxRecordCount": 2,
                })
            if "returnCountOnly" in q:
                return httpx.Response(200, json={"count": count})
            if "returnIdsOnly" in q:
                return httpx.Response(200, json={"objectIds": list(range(count - int(bad_ids)))})
            ids = [int(x) for x in q["objectIds"].split(",")]
            if missing_row:
                ids = ids[:-1]
            return httpx.Response(200, json={"type": "FeatureCollection", "features": [
                {"type": "Feature", "properties": {"OBJECTID": oid},
                 "geometry": {"type":"Point", "coordinates":[-80.3,25.7]}} for oid in ids
            ], "exceededTransferLimit": False})
        return httpx.Client(transport=httpx.MockTransport(handle))

    def test_complete_batches_and_wgs84(self):
        with self.client() as client:
            data = ArcGIS(client).fetch(SOURCES["imdc_power"], limit=0)
        self.assertEqual(data["selection"], "all")
        self.assertEqual(len(data["features"]), 3)
        batches = [q for q in self.queries if "objectIds" in q]
        self.assertEqual(len(batches), 2)
        self.assertTrue(all(q["outSR"] == "4326" for q in batches))

    def test_sample_is_explicit(self):
        with self.client() as client:
            data = ArcGIS(client).fetch(SOURCES["imdc_power"], limit=1)
        self.assertEqual(data["selection"], "sample")
        self.assertEqual(data["total_count"], 3)
        self.assertEqual(data["selected_count"], 1)

    def test_empty_source_is_success_not_failure(self):
        with self.client(count=0) as client:
            data = ArcGIS(client).fetch(SOURCES["imdc_power"])
        self.assertEqual(data["features"], [])
        self.assertTrue(data["complete_for_selection"])

    def test_partial_batch_cannot_export(self):
        with self.client(missing_row=True) as client:
            with self.assertRaisesRegex(SourceError, "Incomplete"):
                ArcGIS(client).fetch(SOURCES["imdc_power"])

    def test_changed_count_cannot_export(self):
        with self.client(bad_ids=True) as client:
            with self.assertRaisesRegex(SourceError, "Count/ID mismatch"):
                ArcGIS(client).fetch(SOURCES["imdc_power"])

    def test_arcgis_error_in_http_success_is_failure(self):
        with self.client(error=True) as client:
            with self.assertRaisesRegex(SourceError, "Bad query"):
                ArcGIS(client).fetch(SOURCES["imdc_power"])

    @patch("backend.ingestion.arcgis.time.sleep")
    def test_transient_error_retried(self, sleep):
        calls = []
        def handle(request):
            calls.append(request)
            return httpx.Response(503 if len(calls) == 1 else 200, json={"count": 1})
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            self.assertEqual(ArcGIS(client).get("https://example.org", f="json"), {"count":1})
        self.assertEqual(len(calls), 2)

    @patch("backend.ingestion.arcgis.time.sleep")
    def test_transport_failure_is_bounded(self, sleep):
        def handle(request):
            raise httpx.ConnectError("offline")
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            with self.assertRaises(SourceError):
                ArcGIS(client).get("https://example.org")
        self.assertEqual(sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()

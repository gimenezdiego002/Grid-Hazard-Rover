"""Integrity only: never import or execute the vendored hardware programs."""

import hashlib
import json
from pathlib import Path


def test_fnk0052_source_matches_recorded_vendor_hashes():
    root = Path(__file__).resolve().parents[1] / "hexapod" / "vendor" / "fnk0052"
    manifest = json.loads((root / "SOURCE.json").read_text(encoding="utf-8"))
    assert manifest["commit"] == "b7d228cc870b0a802d3768bfcf742f85fa8695f6"
    assert manifest["modified"] is False
    assert len(manifest["files"]) == 25
    for name, expected in manifest["files"].items():
        path = (root / name).resolve()
        assert path.is_relative_to(root.resolve())
        content = path.read_bytes()
        assert len(content) == expected["size"]
        assert hashlib.sha256(content).hexdigest() == expected["sha256"]
        git_blob = b"blob " + str(len(content)).encode() + b"\0" + content
        assert hashlib.sha1(git_blob).hexdigest() == expected["blob_sha"]

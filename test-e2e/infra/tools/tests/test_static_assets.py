"""Copy and D0 checks against isolated synthetic fixture trees."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import static_assets as assets


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.home = self.root / "home"
        self.source.mkdir()
        self.catalog = self.root / "catalog.json"

    def fixture(self, name="audio/语音.pcm", content=b"\x01\x00\x02\x00"):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        item = {"asset_id": "AUD-001", "path": name, "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content)}
        self.catalog.write_text(json.dumps({"schema_version": 1, "assets": [item]}, ensure_ascii=False), encoding="utf-8")
        return item

    def test_apply_preserves_bytes_and_second_apply_is_idempotent(self):
        item = self.fixture()
        self.assertEqual(assets.inventory(self.home, source=self.source, catalog=self.catalog)[0]["destination"], "MISSING")
        first = assets.apply(self.home, self.source, self.catalog)
        self.assertEqual(first[0]["destination"], "READY")
        self.assertEqual((self.home / "assets" / item["path"]).read_bytes(), (self.source / item["path"]).read_bytes())
        self.assertEqual(assets.apply(self.home, self.source, self.catalog)[0]["destination"], "READY")
        self.assertTrue((self.home / "state/static-asset-provision.json").is_file())

    def test_conflict_refuses_overwrite(self):
        item = self.fixture()
        destination = self.home / "assets" / item["path"]
        destination.parent.mkdir(parents=True)
        destination.write_bytes(b"different")
        with self.assertRaisesRegex(ValueError, "differ"):
            assets.apply(self.home, self.source, self.catalog)
        self.assertEqual(destination.read_bytes(), b"different")

    def test_source_drift_prevents_copy(self):
        item = self.fixture()
        (self.source / item["path"]).write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "source"):
            assets.apply(self.home, self.source, self.catalog)
        self.assertFalse((self.home / "assets" / item["path"]).exists())

    def test_bad_media_is_not_ready_even_if_hash_matches(self):
        item = self.fixture(name="audio/speech.wav", content=b"not a wave")
        self.assertEqual(assets.inventory(self.home, source=self.source, catalog=self.catalog)[0]["source"],
                         "Invalid WAV header")

    def test_path_traversal_rejected(self):
        item = self.fixture()
        item["path"] = "../other/file.pcm"
        self.catalog.write_text(json.dumps({"schema_version": 1, "assets": [item]}))
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            assets.entries(self.catalog)

    def test_unknown_selection_is_error(self):
        self.fixture()
        with self.assertRaisesRegex(ValueError, "Unknown"):
            assets.inventory(self.home, selected={"AUD-999"}, catalog=self.catalog)

    def test_managed_update_backs_up_old_bytes(self):
        old = self.fixture()
        assets.apply(self.home, self.source, self.catalog)
        self.fixture(content=b"\x03\x00\x04\x00")
        assets.apply(self.home, self.source, self.catalog)
        backup = self.home / "state/static-asset-backups" / old["sha256"] / old["path"]
        self.assertEqual(backup.read_bytes(), b"\x01\x00\x02\x00")
        self.assertEqual((self.home / "assets" / old["path"]).read_bytes(), b"\x03\x00\x04\x00")

    def test_user_modified_managed_asset_is_not_overwritten(self):
        old = self.fixture()
        assets.apply(self.home, self.source, self.catalog)
        destination = self.home / "assets" / old["path"]
        destination.write_bytes(b"\x05\x00")
        self.fixture(content=b"\x03\x00\x04\x00")
        with self.assertRaises(ValueError):
            assets.apply(self.home, self.source, self.catalog)
        self.assertEqual(destination.read_bytes(), b"\x05\x00")


if __name__ == "__main__":
    unittest.main()

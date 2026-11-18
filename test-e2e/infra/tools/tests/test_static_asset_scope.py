# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""A broken fixture blocks its dependent Cases, not unrelated work or code updates."""
import hashlib
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import static_assets as assets
import suite
from suite_runtime import save


@pytest.fixture
def fixtures(tmp_path):
    source, home = tmp_path / "source", tmp_path / "home"
    source.mkdir()
    rows = []
    for name in ("good", "bad"):
        content = (name * 2).encode()
        (source / (name + ".txt")).write_bytes(content)
        rows.append({"asset_id": name, "path": name + ".txt", "bytes": len(content),
                     "sha256": hashlib.sha256(content).hexdigest()})
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"schema_version": 1, "assets": rows}))
    return source, home, catalog, rows


@pytest.mark.parametrize("problem", ["missing", "changed", "conflict", "unreadable"])
def test_daily_provisions_other_fixtures_without_overwriting_bad_input(fixtures, problem):
    source, home, catalog, _ = fixtures
    if problem == "missing":
        (source / "bad.txt").unlink()
    elif problem == "changed":
        (source / "bad.txt").write_bytes(b"source drift")
    elif problem == "conflict":
        (home / "assets").mkdir(parents=True)
        (home / "assets/bad.txt").write_bytes(b"user-owned bytes")
    original = (home / "assets/bad.txt").read_bytes() if (home / "assets/bad.txt").exists() else None
    checksum = assets.sha256

    def sha(path):
        if problem == "unreadable" and path.name == "bad.txt":
            raise PermissionError("fixture read denied")
        return checksum(path)

    with patch.object(assets, "sha256", side_effect=sha):
        result = assets.apply(home, source, catalog, allow_unready=True)
    assert next(row for row in result if row["asset_id"] == "good")["destination"] == "READY"
    assert next(row for row in result if row["asset_id"] == "bad")["destination"] != "READY"
    assert (home / "assets/good.txt").read_bytes() == (source / "good.txt").read_bytes()
    assert ((home / "assets/bad.txt").read_bytes() if (home / "assets/bad.txt").exists() else None) == original


def test_failed_provision_preserves_previous_managed_hash_for_later_retry(fixtures):
    source, home, catalog, rows = fixtures
    assets.apply(home, source, catalog)
    original = rows[1].copy()
    content = b"new fixture version"
    rows[1].update(bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
    catalog.write_text(json.dumps({"schema_version": 1, "assets": rows}))
    (source / "bad.txt").unlink()
    assets.apply(home, source, catalog, allow_unready=True)
    receipt = json.loads((home / "state/static-asset-provision.json").read_text())
    assert next(row for row in receipt["assets"] if row["asset_id"] == "bad")["sha256"] == original["sha256"]
    (source / "bad.txt").write_bytes(content)
    assets.apply(home, source, catalog, allow_unready=True)
    assert (home / "assets/bad.txt").read_bytes() == content
    assert (home / "state/static-asset-backups" / original["sha256"] / "bad.txt").read_bytes() == b"badbad"


def test_partial_provision_does_not_accept_unsafe_catalog_paths(fixtures):
    source, home, catalog, rows = fixtures
    rows[1]["path"] = "../outside.txt"
    catalog.write_text(json.dumps({"schema_version": 1, "assets": rows}))
    with pytest.raises(ValueError, match="Unsafe"):
        assets.apply(home, source, catalog, allow_unready=True)


def test_daily_provision_write_failure_is_scoped_to_its_fixture(fixtures):
    source, home, catalog, _ = fixtures
    link = assets.os.link

    def provision(original, destination):
        if destination.name == "bad.txt":
            raise PermissionError("fixture write denied")
        return link(original, destination)

    with patch.object(assets.os, "link", side_effect=provision):
        result = assets.apply(home, source, catalog, allow_unready=True)
    assert {row["asset_id"]: row["destination"] for row in result} == {
        "good": "READY", "bad": "PROVISION_FAILED"}
    assert not (home / "assets/bad.txt").exists()
    assert not list((home / "assets").glob(".nexent-asset-*"))


@pytest.mark.parametrize("dependency", ["declared", "direct", None])
def test_batch_runs_independent_cases_when_a_fixture_is_unavailable(tmp_path, fixtures, dependency):
    _, home, catalog, rows = fixtures
    repo = tmp_path / "repo"
    records = []
    for name in ("FIRST", "INDEPENDENT"):
        case = repo / "test-e2e/cases" / name
        case.mkdir(parents=True)
        script = "def test_proof(): pass\n"
        if name == "FIRST" and dependency == "direct":
            script += "FIXTURE = 'assets/bad.txt'\n"
        (case / "test.py").write_text(script)
        records.append({"case_id": name, "stage": "D1", "status": "active", "execution": {
            "required_assets": ["bad"] if name == "FIRST" and dependency == "declared" else [],
            "implementations": [{"framework": "pytest", "file": f"test-e2e/cases/{name}/test.py", "selector": "test_proof"}]}})
    calls = []

    def run(command, cwd, env, log, timeout):
        if "--case" in command:
            case_id = command[command.index("--case") + 1]
            calls.append(case_id)
            directory = Path(command[command.index("--batch-dir") + 1])
            save(directory / "cases" / case_id / "receipt.json", {"case_id": case_id, "stage": "D1", "result": "PASS"})
        return 0

    with patch.object(suite, "machine_environment", return_value=dict(os.environ)), \
            patch.object(suite, "fingerprint", return_value={"head": "fixture"}), \
            patch.object(suite, "static_entries", return_value=rows), \
            patch.object(suite, "static_inventory", side_effect=lambda home, **kw: assets.inventory(home, catalog=catalog, **kw)), \
            patch.object(suite, "logged", side_effect=run):
        assert suite.execute(repo, home, records, {"hooks": {}, "case_timeout_seconds": 20}) == int(bool(dependency))
    directory = next((home / "runs/repository-daily").iterdir())
    summary = json.loads((directory / "summary.json").read_text())
    assert summary["execution_complete"]
    assert calls == (["INDEPENDENT"] if dependency else ["FIRST", "INDEPENDENT"])
    assert summary["counts"] == ({"BLOCKED": 1, "PASS": 1} if dependency else {"PASS": 2})

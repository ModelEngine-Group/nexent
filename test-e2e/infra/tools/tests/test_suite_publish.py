# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Offline publication tests; no product calls, synchronization, or notifications."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import suite_publish
from suite_runtime import save


def make_batch(home, name="complete-batch", results=("PASS", "FAIL", "TIMEOUT")):
    batch = home / "runs/repository-daily" / name
    plan = [{"case_id": f"CASE-{index}", "stage": "D4"} for index in range(len(results))]
    rows = [{**record, "result": result, "reason": "diagnostic", "evidence": ["cases/" + record["case_id"]]}
            for record, result in zip(plan, results)]
    save(batch / "plan.json", {"cases": plan})
    save(batch / "summary.json", {"status": "FAILED" if "FAIL" in results else "PASSED", "planned": len(plan),
         "recorded": len(rows), "counts": dict(Counter(results)), "execution_complete": True, "d6_complete": True,
         "finished_at": "2026-10-13T02:06:10+00:00"})
    save(batch / "status.json", {"stages": {f"D{i}": "COMPLETE" for i in range(7)},
         "started_at": "2026-10-12T22:52:22Z"})
    save(batch / "provenance.json", {"head": "a" * 40, "batch_mode": "daily"})
    checkpoint = batch / "checkpoints/results.jsonl"
    checkpoint.parent.mkdir()
    checkpoint.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    for record in plan:
        case = batch / "cases" / record["case_id"]
        save(case / "receipt.json", {"case_id": record["case_id"], "result": "FAIL"})
        (case / "step-1.log").write_text("complete diagnostic log\n", encoding="utf-8")
    (batch / "report.md").write_text("original reading view", encoding="utf-8")
    save(batch / "notification.json", {"status": "SENT"})
    return batch


def test_complete_failed_batch_publishes_full_text_logs_and_keeps_source_unchanged(tmp_path):
    batch = make_batch(tmp_path)
    before = {path.relative_to(batch).as_posix(): path.read_bytes() for path in batch.rglob("*") if path.is_file()}
    receipt = suite_publish.publish_latest(batch, tmp_path)
    assert receipt["status"] == "PUBLISHED"
    assert set(path.name for path in (tmp_path / "runs-ubuntu").iterdir()) == set(suite_publish.MANAGED_FILES)
    with zipfile.ZipFile(tmp_path / "runs-ubuntu/latest-batch.zip") as package:
        manifest = json.loads(package.read("manifest.json"))
        assert manifest["counts"] == {"PASS": 1, "FAIL": 1, "TIMEOUT": 1}
        for item in manifest["files"]:
            assert hashlib.sha256(package.read(item["path"])).hexdigest() == item["sha256"]
        assert "cases/CASE-0/step-1.log" in package.namelist()
        assert "cases/CASE-2/step-1.log" in package.namelist()
        assert "notification.json" not in package.namelist()
        assert package.read("report.md") == (tmp_path / "runs-ubuntu/latest-report.md").read_bytes()
        report = package.read("report.md").decode()
        assert "当前批次：`complete-batch`" in report
        assert "2026-10-13 06:52:22 +08:00" in report
        assert batch.resolve().as_posix() in report
        assert "相对于解压目录" in report
        assert "不是飞书附件" in report
    for name, value in before.items():
        assert (batch / name).read_bytes() == value


def test_repeated_publish_overwrites_only_two_named_files(tmp_path):
    first = make_batch(tmp_path, "first")
    suite_publish.publish_latest(first, tmp_path)
    second = make_batch(tmp_path, "second", ("PASS",))
    suite_publish.publish_latest(second, tmp_path)
    destination = tmp_path / "runs-ubuntu"
    assert len(list(destination.iterdir())) == 2
    with zipfile.ZipFile(destination / "latest-batch.zip") as package:
        assert json.loads(package.read("manifest.json"))["batch_id"] == "second"
        assert "cases/CASE-2/step-1.log" not in package.namelist()
    assert first.exists()


@pytest.mark.parametrize("invalid", ["incomplete", "d6", "stages", "counts", "duplicate", "unknown-result", "local"])
def test_invalid_or_incomplete_batch_never_overwrites_previous(tmp_path, invalid):
    previous = make_batch(tmp_path, "previous")
    suite_publish.publish_latest(previous, tmp_path)
    before = {name: (tmp_path / "runs-ubuntu" / name).read_bytes() for name in suite_publish.MANAGED_FILES}
    batch = make_batch(tmp_path, "invalid")
    summary = json.loads((batch / "summary.json").read_text())
    if invalid == "incomplete": summary["execution_complete"] = False
    if invalid == "d6": summary["d6_complete"] = False
    if invalid == "counts": summary["counts"] = {"PASS": 3}
    save(batch / "summary.json", summary)
    if invalid == "stages": save(batch / "status.json", {"stages": {"D6": "COMPLETE"}})
    if invalid == "duplicate":
        checkpoint = batch / "checkpoints/results.jsonl"
        checkpoint.write_text(checkpoint.read_text() + checkpoint.read_text().splitlines()[0] + "\n")
    if invalid == "unknown-result":
        checkpoint = batch / "checkpoints/results.jsonl"
        checkpoint.write_text(checkpoint.read_text().replace('"TIMEOUT"', '"NOT_EXECUTED"'))
        summary["counts"] = {"PASS": 1, "FAIL": 1, "NOT_EXECUTED": 1}
        save(batch / "summary.json", summary)
    if invalid == "local": save(batch / "provenance.json", {"head": "a" * 40, "batch_mode": "run"})
    with pytest.raises(ValueError): suite_publish.publish_latest(batch, tmp_path)
    assert {name: (tmp_path / "runs-ubuntu" / name).read_bytes() for name in before} == before


def test_configured_and_dynamic_credentials_are_redacted_without_truncating_logs(tmp_path):
    batch = make_batch(tmp_path)
    secret = "configured-credential-123"
    save(tmp_path / "config/users.yaml", {"user": {"password": secret}})
    log = batch / "cases/CASE-1/step-1.log"
    text = ("Authorization: Bearer dynamic-credential-456\nCookie: session=dynamic-cookie-789\n"
            '{"api_key":"inline-credential-111","password":"inline-password-222"}\n'
            "https://user:url-password-333@example.invalid/path\n" + secret + "\n" + "x" * 6000)
    log.write_text(text, encoding="utf-8")
    save(batch / "cases/CASE-1/failure.json", {"headers": {"Authorization": "dynamic-credential-456"}, "message": secret})
    suite_publish.publish_latest(batch, tmp_path)
    with zipfile.ZipFile(tmp_path / "runs-ubuntu/latest-batch.zip") as package:
        for name in package.namelist():
            data = package.read(name).decode()
            for credential in [secret, "dynamic-credential-456", "dynamic-cookie-789", "inline-credential-111",
                               "inline-password-222", "url-password-333"]:
                assert credential not in data
        assert "x" * 6000 in package.read("cases/CASE-1/step-1.log").decode()
        assert secret in log.read_text()


def test_sensitive_assets_and_unreviewed_binary_evidence_stay_local(tmp_path):
    batch = make_batch(tmp_path)
    case = batch / "cases/CASE-1"
    save(case / "runtime/resolved-assets.yaml", {"private": "secret"})
    (case / "password.env").write_text("PASSWORD=secret")
    (case / "failure.png").write_bytes(b"unreviewed image")
    (case / "trace.zip").write_bytes(b"unreviewed trace")
    (batch / "cases/CASE-0/success.png").write_bytes(b"success image")
    suite_publish.publish_latest(batch, tmp_path)
    with zipfile.ZipFile(tmp_path / "runs-ubuntu/latest-batch.zip") as package:
        assert not any(name.endswith((".env", ".yaml", ".png")) or name.endswith("trace.zip") for name in package.namelist())
        excluded = json.loads(package.read("excluded-evidence.json"))
        assert {item["path"] for item in excluded} == {"cases/CASE-1/failure.png", "cases/CASE-1/trace.zip"}
        assert "二进制证据：2 个" in package.read("report.md").decode()


def test_second_replacement_failure_restores_previous_pair(tmp_path):
    suite_publish.publish_latest(make_batch(tmp_path, "previous"), tmp_path)
    before = {name: (tmp_path / "runs-ubuntu" / name).read_bytes() for name in suite_publish.MANAGED_FILES}
    batch = make_batch(tmp_path, "new")
    replace = os.replace
    def fail_report(source, destination):
        if Path(source).name == "latest-report.md": raise OSError("simulated replacement failure")
        return replace(source, destination)
    with patch.object(suite_publish.os, "replace", side_effect=fail_report):
        with pytest.raises(OSError): suite_publish.publish_latest(batch, tmp_path)
    assert {name: (tmp_path / "runs-ubuntu" / name).read_bytes() for name in before} == before


def test_invalid_text_fails_packaging_without_replacing_previous(tmp_path):
    suite_publish.publish_latest(make_batch(tmp_path, "previous"), tmp_path)
    before = (tmp_path / "runs-ubuntu/latest-batch.zip").read_bytes()
    batch = make_batch(tmp_path, "new")
    (batch / "cases/CASE-1/failure.json").write_text("invalid json")
    with pytest.raises(ValueError): suite_publish.publish_latest(batch, tmp_path)
    assert (tmp_path / "runs-ubuntu/latest-batch.zip").read_bytes() == before


def test_unrelated_destination_files_are_preserved_and_do_not_block_republication(tmp_path):
    suite_publish.publish_latest(make_batch(tmp_path, "previous"), tmp_path)
    destination = tmp_path / "runs-ubuntu"
    extracted = destination / "unzip_previous_latest-batch"
    extracted.mkdir()
    (extracted / "report.md").write_text("previous extracted report", encoding="utf-8")
    (destination / "operator-notes.txt").write_text("private operator notes", encoding="utf-8")
    before = {path.relative_to(destination).as_posix(): path.read_bytes()
              for path in destination.rglob("*") if path.is_file() and path.name not in suite_publish.MANAGED_FILES}
    receipt = suite_publish.publish_latest(make_batch(tmp_path, "new"), tmp_path)
    assert receipt["status"] == "PUBLISHED"
    for name, content in before.items():
        assert (destination / name).read_bytes() == content
    with zipfile.ZipFile(destination / "latest-batch.zip") as package:
        assert json.loads(package.read("manifest.json"))["batch_id"] == "new"
        assert not any("unzip_previous" in name or "operator-notes" in name for name in package.namelist())


@pytest.mark.parametrize("name", suite_publish.MANAGED_FILES)
def test_managed_destination_directory_is_rejected_without_replacing_other_file(tmp_path, name):
    destination = tmp_path / "runs-ubuntu"
    (destination / name).mkdir(parents=True)
    other = next(item for item in suite_publish.MANAGED_FILES if item != name)
    (destination / other).write_bytes(b"previous managed content")
    with pytest.raises(ValueError, match="Managed publication targets"):
        suite_publish.publish_latest(make_batch(tmp_path), tmp_path)
    assert (destination / name).is_dir()
    assert (destination / other).read_bytes() == b"previous managed content"


@pytest.mark.parametrize("name", suite_publish.MANAGED_FILES)
@pytest.mark.parametrize("dangling", [False, True])
def test_managed_destination_symlink_is_rejected_without_touching_target(tmp_path, name, dangling):
    destination = tmp_path / "runs-ubuntu"
    destination.mkdir()
    target = tmp_path / "outside-private.txt"
    if not dangling:
        target.write_bytes(b"private outside content")
    try:
        (destination / name).symlink_to(target)
    except OSError:
        pytest.skip("Host does not permit creation of symlinks")
    other = next(item for item in suite_publish.MANAGED_FILES if item != name)
    (destination / other).write_bytes(b"previous managed content")
    with pytest.raises(ValueError, match="Managed publication targets"):
        suite_publish.publish_latest(make_batch(tmp_path), tmp_path)
    assert (destination / name).is_symlink()
    assert (destination / other).read_bytes() == b"previous managed content"
    assert target.exists() == (not dangling)
    if not dangling:
        assert target.read_bytes() == b"private outside content"


def test_wrong_ownership_revision_is_rejected(tmp_path):
    batch = make_batch(tmp_path)
    save(tmp_path / "ownership.json", {"head": "wrong", "cases": []})
    with pytest.raises(ValueError, match="different batch revision"):
        suite_publish.publish_latest(batch, tmp_path, ownership_file=tmp_path / "ownership.json")


def test_source_must_be_owned_daily_directory(tmp_path):
    with pytest.raises(ValueError, match="owned repository Daily"):
        suite_publish.publish_latest(tmp_path / "other", tmp_path)


def test_redaction_must_not_change_result_identity(tmp_path):
    batch = make_batch(tmp_path)
    with pytest.raises(ValueError, match="immutable result identities"):
        suite_publish.publish_latest(batch, tmp_path, {"PASSWORD": "CASE-1"})
    assert not (tmp_path / "runs-ubuntu/latest-batch.zip").exists()


@pytest.mark.parametrize("enabled,fail_publish,fail_import", [
    (False, False, False), (True, False, False), (True, True, False), (True, False, True)])
def test_runner_publish_precedes_notification_without_changing_failure_results(
        tmp_path, enabled, fail_publish, fail_import):
    import suite
    import suite_notify
    calls = []
    record = {"case_id": "A-1", "stage": "D2", "status": "blocked", "execution": None,
              "git_last_modifier": {"status": "UNKNOWN"},
              "responsibility": {"status": "UNASSIGNED"}}
    real_publish = suite_publish.publish_latest
    real_import = __import__
    def import_module(name, *args, **kwargs):
        if fail_import and name == "suite_publish":
            calls.append("publish")
            raise ImportError("simulated publication module load failure")
        return real_import(name, *args, **kwargs)

    def publish(*args, **kwargs):
        calls.append("publish")
        if fail_publish: raise OSError("simulated packaging failure")
        return real_publish(*args, **kwargs)
    def notify(directory, env):
        calls.append("notify")
        summary = json.loads((directory / "summary.json").read_text())
        assert summary["counts"] == {"BLOCKED": 1}
        report = (directory / "report.md").read_text(encoding="utf-8")
        if enabled:
            assert "Syncthing 共享副本" in report
            assert ("上一批次" in report) == (fail_publish or fail_import)
        else:
            assert "Syncthing 共享副本" not in report
        return "SENT"
    settings = {"hooks": {name: [["synthetic-command"]] for name in ("build", "deploy", "preflight")},
                "case_timeout_seconds": 20, "command_timeout_seconds": 20, "notify": True}
    with patch.object(suite, "machine_environment", return_value={}), \
            patch.object(suite, "fingerprint", return_value={"head": "a" * 40}), \
            patch.object(suite, "enrich_ownership", return_value=([record], [])), \
            patch.object(suite, "static_inventory", return_value=[]), \
            patch.object(suite, "logged", return_value=0), \
            patch.object(suite.subprocess, "check_output", return_value=""), \
            patch("builtins.__import__", side_effect=import_module), \
            patch.object(suite_publish, "publish_latest", side_effect=publish), \
            patch.object(suite_notify, "send_report", side_effect=notify):
        assert suite.execute(tmp_path, tmp_path, [record], settings, daily=True, publish_latest=enabled) == 1
    assert calls == (["publish", "notify"] if enabled else ["notify"])
    assert (tmp_path / "runs-ubuntu/latest-batch.zip").exists() == (enabled and not fail_publish and not fail_import)


def test_symlinked_evidence_is_rejected_when_supported(tmp_path):
    batch = make_batch(tmp_path)
    target = tmp_path / "private.txt"
    target.write_text("private")
    try: (batch / "cases/CASE-1/linked.log").symlink_to(target)
    except OSError: pytest.skip("Host does not permit creation of symlinks")
    with pytest.raises(ValueError, match="Symlinked publication"):
        suite_publish.publish_latest(batch, tmp_path)

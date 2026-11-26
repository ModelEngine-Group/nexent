# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""CHAT-TRAJECTORY-ARCHIVE-D2-001: actual HTTP archive contracts."""

import io
import zipfile
from dataclasses import replace

import pytest
from ops.api import trajectory as api
from ops.services.trajectory.exchange import ExchangeLimits
from trajectory_exchange import change_meta, exported, http_app, imported, rewrite, seed

pytestmark = [
    pytest.mark.case_id("CHAT-TRAJECTORY-ARCHIVE-D2-001"),
    pytest.mark.stage("D2"),
]


def test_archive_http_contract(tmp_path, monkeypatch):
    source = seed(tmp_path)
    with http_app(monkeypatch, source) as http:
        first = http.client.get(
            "/trajectory/conversations/123",
            params={"limit": 1},
            headers={"Authorization": "admin"},
        )
        assert len(first.json()["data"]["executions"]) == 1
        response = exported(http)
        assert response.headers["content-type"] == "application/zip"
        assert response.headers["content-length"] == str(len(response.content))
        assert (
            response.headers["content-disposition"]
            == 'attachment; filename="trajectory-123.zip"'
        )
        assert response.headers["cache-control"] == "private,no-store"
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert set(archive.namelist()) == {
                "source/owner/7/123/meta.json",
                *(f"source/owner/7/123/{run}.otlp.jsonl" for run in source.runs),
            }
        for actor, status in ((None, 401), ("user", 403), ("other", 404)):
            denied = http.client.post(
                "/trajectory/conversations/123/export",
                headers={"Authorization": actor} if actor else {},
            )
            assert (
                denied.status_code == status
                and denied.headers["cache-control"] == "private,no-store"
            )
            assert "Archive" not in denied.text
        assert imported(http, response.content, actor="user").status_code == 403
        assert imported(http, response.content, actor=None).status_code == 401
        assert (
            http.client.post(
                "/trajectory/conversations/invalid/export",
                headers={"Authorization": "admin"},
            ).status_code
            == 422
        )
        limits = ExchangeLimits()
        monkeypatch.setattr(
            api, "configured_limits", lambda: replace(limits, compressed_bytes=100)
        )
        assert exported_too_large(http) == 413
        assert imported(http, response.content).status_code == 413


def exported_too_large(http):
    return http.client.post(
        "/trajectory/conversations/123/export", headers={"Authorization": "admin"}
    ).status_code


def test_archive_http_import_validation(tmp_path, monkeypatch):
    source = seed(tmp_path)
    with http_app(monkeypatch, source) as http:
        raw = exported(http).content
    with http_app(monkeypatch) as target:
        response = imported(target, raw)
        assert (
            response.status_code == 200
            and response.headers["cache-control"] == "private,no-store"
        )
        assert len(response.json()["data"]["pages"]) == 3
        for edit in (
            lambda entries: change_meta(
                entries, lambda meta: meta.update(schema_version=2)
            ),
            lambda entries: entries.pop(
                next(name for name in entries if name.endswith("jsonl"))
            ),
            lambda entries: entries.update(
                {next(name for name in entries if name.endswith("jsonl")): b"invalid"}
            ),
            lambda entries: change_meta(
                entries, lambda meta: meta.update(owner_user_id="someone")
            ),
        ):
            invalid = imported(target, rewrite(raw, edit))
            assert invalid.status_code == 422
            assert "data" not in invalid.json()
        assert imported(target, b"broken").status_code == 422


def test_archive_http_missing_states_and_snapshot_recheck(tmp_path, monkeypatch):
    source = seed(tmp_path)
    with source.store._session(source.owner) as directory:
        meta = directory.read_json("meta.json")
        meta["runs"][0].update(capture_state="incomplete")
        meta["runs"][1].update(capture_state="expired", cleanup_reason="retention")
        meta["runs"][2].update(capture_state="writing", publication_no=None)
        source.store._save_manifest(directory, meta)
    with http_app(monkeypatch, source) as http:
        raw = exported(http).content
        response = imported(http, raw)
        assert [
            page["run"]["availability"] for page in response.json()["data"]["pages"]
        ] == ["partial", "expired", "unarchived"]
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            assert len(archive.namelist()) == 2
        original = source.service.recheck

        def changed(actor, row):
            with source.store._session(source.owner) as directory:
                current = directory.read_json("meta.json")
                current["cleanup_version"] += 1
                source.store._save_manifest(directory, current)
            return original(actor, row)

        monkeypatch.setattr(source.service, "recheck", changed)
        assert (
            http.client.post(
                "/trajectory/conversations/123/export",
                headers={"Authorization": "admin"},
            ).status_code
            == 409
        )
        with source.store._session(source.owner) as directory:
            current = directory.read_json("meta.json")
            current["runs"][0].update(capture_state="expired", cleanup_reason="manual")
            source.store._save_manifest(directory, current)
        assert (
            http.client.post(
                "/trajectory/conversations/123/export",
                headers={"Authorization": "admin"},
            ).status_code
            == 409
        )

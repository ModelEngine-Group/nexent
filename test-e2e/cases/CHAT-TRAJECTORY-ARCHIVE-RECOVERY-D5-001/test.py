# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""CHAT-TRAJECTORY-ARCHIVE-RECOVERY-D5-001: bounded faults and owned cleanup."""

import asyncio
import os
import shutil
import subprocess
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
from ops.api import trajectory as api
from ops.services.trajectory import exchange
from ops.services.trajectory.primitives import CURRENT_CANCEL, QueryError
from trajectory_exchange import exported, http_app, imported, seed

pytestmark = [
    pytest.mark.case_id("CHAT-TRAJECTORY-ARCHIVE-RECOVERY-D5-001"),
    pytest.mark.stage("D5"),
]


def test_archive_recovery_limits_and_owned_files(tmp_path, monkeypatch):
    source = seed(tmp_path)
    with http_app(monkeypatch, source) as http:
        raw = exported(http).content
        limits = exchange.ExchangeLimits()
        files = []
        temporary = exchange.tempfile.TemporaryFile

        def tracked(*args, **kwargs):
            file = temporary(*args, **kwargs)
            files.append(file)
            return file

        monkeypatch.setattr(exchange.tempfile, "TemporaryFile", tracked)
        for key, value in (
            ("compressed_bytes", len(raw) - 1),
            ("unpacked_bytes", 1),
            ("meta_bytes", 1),
            ("files", 3),
            ("response_bytes", 100),
        ):
            with monkeypatch.context() as patch:
                patch.setattr(
                    api,
                    "configured_limits",
                    lambda key=key, value=value: replace(limits, **{key: value}),
                )
                assert imported(http, raw).status_code == 413
                assert all(file.closed for file in files)
            assert imported(http, raw).status_code == 200
            assert all(file.closed for file in files)
        with monkeypatch.context() as patch:
            patch.setattr(
                api,
                "configured_limits",
                lambda: replace(limits, compressed_bytes=len(raw), files=4),
            )
            assert imported(http, raw).status_code == 200
        with monkeypatch.context() as patch:
            patch.setattr(
                exchange.tempfile,
                "TemporaryFile",
                lambda: (_ for _ in ()).throw(OSError("controlled disk fault")),
            )
            assert imported(http, raw).status_code == 503
        assert imported(http, raw).status_code == 200
        with monkeypatch.context() as patch:
            original = exchange._read_entry

            def cancelled(*args, **kwargs):
                event = CURRENT_CANCEL.get()
                event.set()
                return original(*args, **kwargs)

            patch.setattr(exchange, "_read_entry", cancelled)
            started = time.monotonic()
            assert imported(http, raw).status_code == 503
            assert time.monotonic() - started < 5
            assert all(file.closed for file in files)
        assert imported(http, raw).status_code == 200


def test_archive_recovery_disconnect_cancels_export(tmp_path, monkeypatch):
    source = seed(tmp_path)
    with http_app(monkeypatch, source) as http:
        started, ended = threading.Event(), threading.Event()

        def wait_for_disconnect(*args, **kwargs):
            cancel = CURRENT_CANCEL.get()
            started.set()
            try:
                assert cancel.wait(3)
                raise QueryError("query_budget_exceeded", 503)
            finally:
                ended.set()

        with monkeypatch.context() as patch:
            patch.setattr(api, "export_conversation", wait_for_disconnect)

            async def call():
                from starlette.requests import Request

                async def receive():
                    while not started.is_set():
                        await asyncio.sleep(0.01)
                    return {"type": "http.disconnect"}

                request = Request({"type": "http", "app": http.app}, receive)
                with pytest.raises(asyncio.CancelledError):
                    await api.export_trajectory(request, "123", "admin")

            asyncio.run(call())
            assert ended.wait(3)
        assert exported(http).status_code == 200
        source.catalog.revoked = True
        denied = http.client.post(
            "/trajectory/conversations/123/export", headers={"Authorization": "admin"}
        )
        assert denied.status_code in (403, 404)
        source.catalog.revoked = False
        assert exported(http).status_code == 200


def test_archive_recovery_browser():
    result = subprocess.run(
        [shutil.which("node"), "--test", str(Path(__file__).with_name("browser.mjs"))],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
        env=dict(os.environ),
    )
    assert result.returncode == 0, result.stdout + result.stderr

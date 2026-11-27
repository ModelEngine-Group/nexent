# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""CHAT-TRAJECTORY-ARCHIVE-SECURITY-D5-001: adversarial archives at HTTP boundary."""

import io
import json
import stat
import zipfile
from dataclasses import replace

import pytest
from ops.api import trajectory as api
from ops.services.trajectory.exchange import ExchangeLimits
from trajectory_exchange import change_meta, exported, http_app, imported, rewrite, seed

pytestmark = [
    pytest.mark.case_id("CHAT-TRAJECTORY-ARCHIVE-SECURITY-D5-001"),
    pytest.mark.stage("D5"),
]


def test_archive_security_malformed_inputs_and_recovery(tmp_path, monkeypatch):
    source = seed(tmp_path)
    with http_app(monkeypatch, source) as http:
        raw = exported(http).content

    def corrupt_spans(entries):
        name = next(name for name in entries if name.endswith("jsonl"))
        requests = [json.loads(line) for line in entries[name].splitlines()]
        spans = requests[0]["resourceSpans"][0]["scopeSpans"][0]["spans"]
        for span in spans:
            if span["name"].startswith("Archive"):
                span["attributes"].append(
                    {
                        "key": "nexent.parent_record_id",
                        "value": {"stringValue": "node-3"},
                    }
                )
        import hashlib

        entries[name] = (
            b"\n".join(json.dumps(request).encode() for request in requests) + b"\n"
        )

        def update(meta):
            run = next(run for run in meta["runs"] if run["trajectory_id"] in name)
            run.update(
                confirmed_bytes=len(entries[name]),
                confirmed_sha256=hashlib.sha256(entries[name]).hexdigest(),
            )

        change_meta(entries, update)

    variants = [
        rewrite(raw, lambda entries: entries.update({"../outside": b"escape"})),
        rewrite(raw, lambda entries: entries.update({"/absolute": b"escape"})),
        rewrite(
            raw, lambda entries: entries.update({"source/owner/7/123/nested.zip": raw})
        ),
        rewrite(
            raw,
            lambda entries: change_meta(
                entries, lambda meta: meta.update(schema_version=100)
            ),
        ),
        rewrite(raw, corrupt_spans),
    ]
    for mode in ("duplicate", "symlink", "encrypted", "crc"):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_STORED) as archive:
            with zipfile.ZipFile(io.BytesIO(raw)) as original:
                for item in original.infolist():
                    archive.writestr(item.filename, original.read(item))
            if mode == "duplicate":
                archive.writestr("source/owner/7/123/meta.json", b"{}")
            if mode == "symlink":
                item = zipfile.ZipInfo("source/owner/7/123/link")
                item.create_system = 3
                item.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(item, "../../outside")
        data = bytearray(output.getvalue())
        if mode == "encrypted":
            position = data.index(b"PK\x01\x02")
            data[position + 8] |= 1
        if mode == "crc":
            position = data.index(b"PK\x01\x02")
            data[position + 16] ^= 1
        variants.append(bytes(data))
    with http_app(monkeypatch) as target:
        for value in variants:
            response = imported(target, value)
            assert response.status_code == 422, response.text
            assert "data" not in response.json()
            assert imported(target, raw).status_code == 200
        limits = ExchangeLimits()
        monkeypatch.setattr(
            api, "configured_limits", lambda: replace(limits, unpacked_bytes=100)
        )
        assert imported(target, raw).status_code == 413
    assert not (tmp_path.parent / "outside").exists()


def test_archive_security_browser():
    import os
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    result = subprocess.run(
        [shutil.which("node"), "--test", str(Path(__file__).with_name("browser.mjs"))],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "FIXED_TEST_PYTHON": sys.executable},
    )
    assert result.returncode == 0, result.stdout + result.stderr

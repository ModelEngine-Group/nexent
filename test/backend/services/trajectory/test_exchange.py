# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Archive exchange preserves native files and rejects invalid input atomically."""

import hashlib
import io
import json
import zipfile
from unittest.mock import Mock
from uuid import uuid4

import pytest
from infrastructure.observability.trajectory_store import (
    CaptureIdentity,
    TrajectoryFileStore,
)
from ops.services.trajectory.access import Actor
from ops.services.trajectory.exchange import (
    ExchangeLimits,
    export_conversation,
    import_archive,
)
from ops.services.trajectory.primitives import QueryError, ReferenceStore
from ops.services.trajectory.service import TrajectoryService

BODY = '中文😀\\\n"' * 12000
ACTOR = Actor("admin", "t", "OPS")


@pytest.fixture
def source(tmp_path):
    store = TrajectoryFileStore(tmp_path / "traces", authorize=lambda _: None)
    owner = CaptureIdentity("t", "u", "1", "7")
    for index in range(3):
        run_id = str(uuid4())
        attrs = {
            "tenant.id": "t",
            "nexent.owner_user_id": "u",
            "conversation.id": "1",
            "nexent.trajectory_id": run_id,
            "openinference.span.kind": "AGENT",
            "nexent.record_id": "root",
            "output.value": BODY,
            "session.id": "1",
            "nexent.trace_id": "1",
        }
        span = {
            "traceId": "a" * 32,
            "spanId": "1" * 16,
            "name": f"Agent {index}",
            "startTimeUnixNano": "1000000000",
            "endTimeUnixNano": "2000000000",
            "attributes": [
                {"key": key, "value": {"stringValue": value}}
                for key, value in attrs.items()
            ],
        }
        with store.start(owner, run_id, str(uuid4()), core_type="smolagents") as writer:
            writer.append(
                [{"resourceSpans": [{"scopeSpans": [{"spans": [span]}]}]}],
                batch_id=str(uuid4()),
                expected_offset=0,
            )
            writer.finish("completed")
    catalog = Mock()
    catalog.tenants.return_value = ["t"]
    catalog.actor_active.return_value = True
    catalog.resolve.return_value = {
        "tenant_id": "t",
        "user_id": "u",
        "user_name": "Owner",
        "conversation_id": "1",
        "conversation_title": "Title",
        "agent_id": "7",
    }
    return TrajectoryService(store, catalog, ReferenceStore()), owner


def repack(raw, transform):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = {item.filename: archive.read(item) for item in archive.infolist()}
    transform(entries)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in entries.items():
            archive.writestr(name, body)
    return output.getvalue()


def test_export_preserves_every_native_run_and_full_unicode(source):
    service, owner = source
    raw = export_conversation(service, ACTOR, "1")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert len(archive.namelist()) == 4
        meta = json.loads(archive.read("t/u/7/1/meta.json"))
        for run in meta["runs"]:
            name = f"t/u/7/1/{run['trajectory_id']}.otlp.jsonl"
            body = archive.read(name)
            assert body == (service.archive.store.root / name).read_bytes()
            assert hashlib.sha256(body).hexdigest() == run["confirmed_sha256"]
    result = import_archive(io.BytesIO(raw))
    assert len(result["pages"]) == 3
    for page in result["pages"]:
        body = page["snapshot"]["nodes"][0]["output"]
        assert body["text"] == BODY and body["complete"] and body["content_id"] is None
    assert result["row"]["conversation_id"] == owner.conversation_id


@pytest.mark.parametrize(
    "kind",
    ["traversal", "extra", "missing", "hash", "version", "ownership", "duplicate"],
)
def test_invalid_packages_are_rejected_without_partial_results(source, kind):
    raw = export_conversation(source[0], ACTOR, "1")

    def change(entries):
        meta_name = "t/u/7/1/meta.json"
        meta = json.loads(entries[meta_name])
        run_name = next(name for name in entries if name.endswith("jsonl"))
        if kind == "traversal":
            entries["../meta.json"] = entries.pop(meta_name)
        elif kind == "extra":
            entries["t/u/7/1/unrelated.txt"] = b"no"
        elif kind == "missing":
            del entries[run_name]
        elif kind == "hash":
            entries[run_name] += b" "
        else:
            if kind == "version":
                meta["schema_version"] = 999
            elif kind == "ownership":
                meta["tenant_id"] = "other"
            elif kind == "duplicate":
                meta["runs"].append(meta["runs"][0])
            entries[meta_name] = json.dumps(meta).encode()

    with pytest.raises(QueryError) as error:
        import_archive(io.BytesIO(repack(raw, change)))
    assert error.value.status == 422


def test_offline_import_ignores_source_retention_date(source):
    raw = export_conversation(source[0], ACTOR, "1")

    def change(entries):
        meta = json.loads(entries["t/u/7/1/meta.json"])
        for run in meta["runs"]:
            run["expires_at"] = "2000-01-01T00:00:00Z"
        entries["t/u/7/1/meta.json"] = json.dumps(meta).encode()

    assert len(import_archive(io.BytesIO(repack(raw, change)))["pages"]) == 3


def test_size_limit_and_empty_archive_are_explicit(source):
    with pytest.raises(QueryError) as error:
        export_conversation(
            source[0], ACTOR, "1", limits=ExchangeLimits(unpacked_bytes=100)
        )
    assert error.value.status == 413
    with pytest.raises(QueryError) as error:
        import_archive(io.BytesIO(b"invalid"))
    assert error.value.status == 422


def test_export_rechecks_authorization_before_returning(source):
    service, _ = source
    service.catalog.resolve.side_effect = [
        service.catalog.resolve.return_value,
        QueryError("trajectory_not_found", 404),
    ]
    with pytest.raises(QueryError) as error:
        export_conversation(service, ACTOR, "1")
    assert error.value.status == 404


def test_export_retention_does_not_rewrite_source_metadata(source):
    service, owner = source
    with service.archive.store._session(owner) as directory:
        meta = directory.read_json("meta.json")
        for run in meta["runs"]:
            run["finished_at"] = "2000-01-01T00:00:00Z"
            run["expires_at"] = "2099-01-01T00:00:00Z"
        service.archive.store._save_manifest(directory, meta)
    path = service.archive.store.root / "t/u/7/1/meta.json"
    before = path.read_bytes()
    with pytest.raises(QueryError) as error:
        export_conversation(service, ACTOR, "1")
    assert error.value.code == "nothing_to_export"
    assert path.read_bytes() == before

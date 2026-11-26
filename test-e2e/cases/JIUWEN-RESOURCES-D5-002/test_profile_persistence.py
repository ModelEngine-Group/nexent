# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Real PostgreSQL migration and management transaction verification in an isolated container."""

import asyncio
import json
import subprocess
import sys
import threading
import time
import uuid
from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "sdk"), str(ROOT / "backend")]

pytestmark = [pytest.mark.case_id("JIUWEN-RESOURCES-D5-002"), pytest.mark.stage("D5")]


def docker(*args):
    result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=40, check=False,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise AssertionError("Isolated PostgreSQL container command failed")
    return result.stdout.strip()


def test_trusted_outlet_postgres_lifecycle(monkeypatch):
    # No application connection settings are used for test writes.
    name = "codex-jiuwen-profile-" + uuid.uuid4().hex[:10]
    docker("image", "inspect", "postgres:15-alpine", "--format", "{{.Id}}")
    docker("run", "-d", "--name", name, "-p", "127.0.0.1::5432",
           "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "postgres:15-alpine")
    engine = None
    try:
        port = int(docker("port", name, "5432/tcp").rsplit(":", 1)[1])
        for _ in range(150):
            result = subprocess.run(["docker", "exec", name, "pg_isready", "-U", "postgres"],
                                    capture_output=True, timeout=5, check=False,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode == 0:
                break
            time.sleep(.1)
        else:
            raise AssertionError("Isolated PostgreSQL did not become ready")
        engine = create_engine(f"postgresql://postgres@127.0.0.1:{port}/postgres", echo=False)
        from infrastructure.rdb import client
        from infrastructure.rdb.client import get_db_session
        from management.db.models import ModelRecord
        from management.db.model.repository import create_model_record, get_model_by_model_id
        from management.db.model.outlets import create_resolved_model_record, update_resolved_model_record
        from management.services.model.adapter import restore_model_snapshot
        from management.services.model.outlet_legacy import create_legacy_llm_outlet, update_legacy_llm_outlet
        from management.services.model.outlet_migration import migrate_legacy_outlets, build_legacy_outlet_snapshot
        from management.services.model.legacy_snapshot import model_source_fingerprint
        from contracts.errors.exceptions import ModelOutletConflictError
        from nexent.core.model_service.profiles.outlet_storage import encode_resolved_model_profile
        from nexent.core.model_service.registry import model_service_references
        from sqlalchemy import inspect

        monkeypatch.setattr(client.db_client, "session_maker", sessionmaker(bind=engine))
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA nexent"))
        ModelRecord.__table__.create(engine)
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE nexent.model_record_t ALTER COLUMN model_id SET DEFAULT "
                                    "nextval('nexent.model_record_t_model_id_seq')"))
        assert "runtime_outlet_snapshot" not in {c["name"] for c in inspect(engine).get_columns("model_record_t", schema="nexent")}
        data = {"model_type": "llm", "model_name": "qwen3.5-plus", "model_repo": "",
            "display_name": "managed", "model_factory": "alibaba-cn", "api_key": "fixture-credential",
            "base_url": "http://127.0.0.1:9999/v1", "max_output_tokens": 512,
            "default_output_reserve_tokens": 256, "extra_params": {"enable_thinking": False}}
        managed_id = create_legacy_llm_outlet(data, "actor", "tenant")
        before = get_model_by_model_id(managed_id, "tenant")
        captured = restore_model_snapshot(before, "tenant")
        assert captured.config_revision == 1 and captured.outlet_id == managed_id
        assert "fixture-credential" not in json.dumps(before["resolved_profile"])
        assert migrate_legacy_outlets(dry_run=True)["items"] == []
        assert migrate_legacy_outlets()["items"] == []
        assert get_model_by_model_id(managed_id, "other") is None
        with pytest.raises(ValueError):
            restore_model_snapshot(before, "other")

        # Exercise the existing generic legacy migration when no optional column exists.
        assert create_model_record({**data, "display_name": "no-envelope"}, "actor", "tenant")
        preview = migrate_legacy_outlets(dry_run=True)
        plain_id = preview["items"][0]["model_id"]
        assert preview["ready"] == 1 and get_model_by_model_id(plain_id, "tenant")["profile_schema_version"] is None
        assert migrate_legacy_outlets()["migrated"] == 1
        assert migrate_legacy_outlets()["items"] == []
        assert restore_model_snapshot(get_model_by_model_id(plain_id, "tenant"), "tenant").outlet_id == plain_id

        # Reproduce an already-deployed optional column, never a required product migration.
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE nexent.model_record_t ADD COLUMN runtime_outlet_snapshot JSONB"))
        frozen = {}
        for label in ("frozen", "stale", "tampered"):
            assert create_model_record({**data, "display_name": label}, "actor", "tenant")
            with engine.connect() as connection:
                model_id = connection.execute(select(ModelRecord.model_id).where(ModelRecord.display_name == label)).scalar_one()
            old = get_model_by_model_id(model_id, "tenant")
            from configs.model_catalog_loader import resolve_reasoning_capability
            profile = build_legacy_outlet_snapshot(old, legacy_capability=resolve_reasoning_capability(
                old["model_name"], old["base_url"], old["model_factory"]), migrated_at="2026-11-16T00:00:00Z")
            if label == "frozen":
                profile = type(profile).model_validate({**profile.model_dump(), "config_revision": 4})
            encoded = encode_resolved_model_profile(profile, registered_references=model_service_references())
            envelope = {"version": 1, "revision": profile.config_revision,
                "source_fingerprint": model_source_fingerprint(old), "row": encoded}
            if label == "stale":
                envelope["source_fingerprint"] = "stale"
            if label == "tampered":
                envelope["row"]["tenant_id"] = "other"
            with engine.begin() as connection:
                connection.execute(text("UPDATE nexent.model_record_t SET runtime_outlet_snapshot=CAST(:payload AS jsonb) WHERE model_id=:id"),
                    {"id": model_id, "payload": json.dumps(envelope)})
            frozen[label] = (model_id, profile, envelope)
        # Canonical configuration always wins over an obsolete or corrupt envelope.
        with engine.begin() as connection:
            connection.execute(text("UPDATE nexent.model_record_t SET runtime_outlet_snapshot='{}'::jsonb WHERE model_id=:id"), {"id": managed_id})
        monkeypatch.setattr("management.services.model.profiles.get_model_profile_catalog",
            lambda: pytest.fail("Frozen model was reinterpreted against a catalog"))
        preview = migrate_legacy_outlets(dry_run=True)
        assert preview["ready"] == 1 and preview["failed"] == 2
        assert get_model_by_model_id(frozen["frozen"][0], "tenant")["profile_schema_version"] is None
        result = migrate_legacy_outlets()
        assert result["migrated"] == 1 and result["failed"] == 2
        assert "fixture-credential" not in json.dumps(result)
        imported = get_model_by_model_id(frozen["frozen"][0], "tenant")
        assert restore_model_snapshot(imported, "tenant").model_dump() == frozen["frozen"][1].model_dump()
        assert imported["api_key"] == "fixture-credential"
        assert restore_model_snapshot(get_model_by_model_id(managed_id, "tenant"), "tenant").model_dump() == captured.model_dump()
        assert migrate_legacy_outlets()["migrated"] == 0
        for label in ("stale", "tampered"):
            rejected = get_model_by_model_id(frozen[label][0], "tenant")
            assert rejected["profile_schema_version"] is None and rejected["temperature"] is None
            assert "migration_error" in rejected["resolved_profile"]
        with engine.connect() as connection:
            saved_envelope = connection.execute(text("SELECT runtime_outlet_snapshot FROM nexent.model_record_t WHERE model_id=:id"),
                {"id": frozen["frozen"][0]}).scalar_one()
            assert saved_envelope == frozen["frozen"][2]

        # Runtime and ordinary management must still work after the obsolete column is removed.
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE nexent.model_record_t DROP COLUMN runtime_outlet_snapshot"))
        assert restore_model_snapshot(get_model_by_model_id(managed_id, "tenant"), "tenant").outlet_id == managed_id
        update_legacy_llm_outlet(before, {"temperature": .2}, "actor", "tenant")
        current = restore_model_snapshot(get_model_by_model_id(managed_id, "tenant"), "tenant")
        assert current.config_revision == 2 and current.parameter_values["temperature"] == .2
        with pytest.raises(ModelOutletConflictError):
            update_legacy_llm_outlet(before, {"temperature": .9}, "actor", "tenant")

        # Two real writers sharing a revision cannot silently overwrite each other.
        barrier = threading.Barrier(2)
        outcomes = []
        from nexent.core.concurrency import LanePolicy, ManagedTaskSpec, ThreadManager
        manager = ThreadManager("canonical-profile-race", {
            "model-tool-io": LanePolicy(name="model-tool-io", max_workers=2, max_queue_size=2)})
        manager.start()
        def save(value):
            row = get_model_by_model_id(managed_id, "tenant")
            barrier.wait(timeout=5)
            try:
                update_legacy_llm_outlet(row, {"temperature": value}, "actor", "tenant")
                outcomes.append("saved")
            except ModelOutletConflictError:
                outcomes.append("conflict")
        try:
            tasks = [manager.submit("model-tool-io", ManagedTaskSpec(task_name="save", owner=__name__), save, value)
                for value in (.3, .4)]
            for task in tasks:
                task.future.result(timeout=15)
        finally:
            assert not asyncio.run(manager.shutdown(timeout=5)).stuck_execution_ids
        assert sorted(outcomes) == ["conflict", "saved"]
        stable = get_model_by_model_id(managed_id, "tenant")
        stable_profile = restore_model_snapshot(stable, "tenant")
        assert stable_profile.config_revision == 3
        # The public update applies the shared outlet-only output policy once;
        # later concurrent updates must retain those saved rules and capabilities.
        assert stable_profile.parameter_rules == current.parameter_rules
        assert stable_profile.capabilities == current.capabilities

        # Caller-owned transactions roll back both the row and complete configuration.
        data = stable_profile.model_dump()
        data["outlet_id"] = None
        data["config_revision"] = 1
        data["connection"]["credential_ref"]["model_id"] = None
        data["identity"]["display_name"] = "must-rollback"
        new_profile = type(stable_profile).model_validate(data)
        with pytest.raises(ValueError, match="controlled rollback"):
            with get_db_session() as session:
                create_resolved_model_record(new_profile, "actor", "tenant", registered_references=model_service_references(),
                    api_key="fixture-credential", db_session=session)
                update_resolved_model_record(stable_profile, 3, "actor", "tenant", registered_references=model_service_references(), db_session=session)
                raise ValueError("controlled rollback")
        assert restore_model_snapshot(get_model_by_model_id(managed_id, "tenant"), "tenant").model_dump() == stable_profile.model_dump()
        with engine.connect() as connection:
            assert connection.execute(select(ModelRecord.model_id).where(ModelRecord.display_name == "must-rollback")).first() is None
    finally:
        if engine is not None:
            engine.dispose()
        docker("rm", "-f", name)

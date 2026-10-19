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
        from database import client
        from database.db_models import ModelRecord
        from database.model_management_db import create_model_record as create_legacy
        from database.model_management_db import get_model_by_model_id
        from database.model_management_db import update_model_record as update_legacy
        from database.model_runtime_profile_db import provision_runtime_outlet_batch
        from services.model_runtime_provisioning_service import (
            build_runtime_outlet_snapshot,
            create_model_record,
            update_model_record,
        )
        from services.model_runtime_snapshot_service import (
            restore_runtime_model_snapshot,
        )

        monkeypatch.setattr(client.db_client, "session_maker", sessionmaker(bind=engine))
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA nexent"))
        ModelRecord.__table__.create(engine)
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE nexent.model_record_t ALTER COLUMN model_id SET DEFAULT "
                                    "nextval('nexent.model_record_t_model_id_seq')"))
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE nexent.model_record_t DROP COLUMN runtime_outlet_snapshot"))
            connection.execute(text("INSERT INTO nexent.model_record_t "
                "(model_name,model_type,model_repo,display_name,tenant_id,base_url,delete_flag) "
                "VALUES ('custom-model','llm','','legacy','tenant','http://127.0.0.1:9999/v1','N')"))
        migration = ROOT / "deploy/sql/migrations/v2.7.2_1015_runtime_outlet_snapshot.sql"
        ddl = migration.read_text(encoding="utf-8")
        with engine.begin() as connection:
            connection.exec_driver_sql(ddl)
            connection.exec_driver_sql(ddl)
        with engine.connect() as connection:
            legacy_id = connection.execute(text("SELECT model_id FROM nexent.model_record_t")).scalar_one()
            assert connection.execute(text("SELECT count(*) FROM nexent.model_record_t")).scalar_one() == 1
        initial = get_model_by_model_id(legacy_id, "tenant")
        assert initial["runtime_outlet_snapshot"] is None
        assert provision_runtime_outlet_batch(build_runtime_outlet_snapshot)[0]["status"] == "migrated"
        assert get_model_by_model_id(legacy_id, "tenant")["runtime_outlet_snapshot"] is None
        assert provision_runtime_outlet_batch(build_runtime_outlet_snapshot, dry_run=False)[0]["status"] == "migrated"
        assert provision_runtime_outlet_batch(build_runtime_outlet_snapshot, dry_run=False)[0]["status"] == "ready"
        legacy = get_model_by_model_id(legacy_id, "tenant")
        assert restore_runtime_model_snapshot(legacy, "tenant").capabilities.tools.status == "unsupported"

        data = {"model_type": "llm", "model_name": "qwen3.5-plus", "model_repo": "",
                "display_name": "managed", "model_factory": "alibaba-cn", "api_key": "fixture-credential",
                "base_url": "http://127.0.0.1:9999/v1", "max_output_tokens": 512,
                "default_output_reserve_tokens": 256, "extra_params": {"enable_thinking": False}}
        assert create_model_record(data, "actor", "tenant") is True
        with engine.connect() as connection:
            managed_id = connection.execute(select(ModelRecord.model_id)
                .where(ModelRecord.display_name == "managed")).scalar_one()
        before = get_model_by_model_id(managed_id, "tenant")
        captured = restore_runtime_model_snapshot(before, "tenant")
        assert captured.config_revision == 1
        assert "fixture-credential" not in json.dumps(before["runtime_outlet_snapshot"])
        assert update_model_record(managed_id, {"temperature": .2}, "actor", "other") is False
        assert get_model_by_model_id(managed_id, "other") is None
        assert update_model_record(managed_id, {"temperature": .2}, "actor", "tenant") is True
        after = get_model_by_model_id(managed_id, "tenant")
        current = restore_runtime_model_snapshot(after, "tenant")
        assert current.config_revision == 2 and current.parameter_values["temperature"] == .2
        assert captured.config_revision == 1 and captured.parameter_values["temperature"] is None
        monkeypatch.setattr("services.model_profile_service.get_model_profile_catalog",
                            lambda: pytest.fail("Saved outlet was reinterpreted against catalog"))
        from nexent.core.concurrency import LanePolicy, ManagedTaskSpec, ThreadManager

        entered, release = threading.Event(), threading.Event()
        manager = ThreadManager("profile-save-race", {
            "model-tool-io": LanePolicy(name="model-tool-io", max_workers=2, max_queue_size=2)})
        manager.start()

        def held_builder(row):
            entered.set()
            assert release.wait(3)
            return build_runtime_outlet_snapshot(row)

        try:
            first = manager.submit("model-tool-io", ManagedTaskSpec(task_name="first-save", owner=__name__),
                update_legacy, managed_id, {"temperature": .3}, "actor", "tenant", runtime_profile_builder=held_builder)
            assert entered.wait(3)
            second = manager.submit("model-tool-io", ManagedTaskSpec(task_name="second-save", owner=__name__),
                update_model_record, managed_id, {"top_p": .8}, "actor", "tenant")
            time.sleep(.05)
            assert not second.future.done()
            release.set()
            assert first.future.result(timeout=3) and second.future.result(timeout=3)
        finally:
            release.set()
            assert not asyncio.run(manager.shutdown(timeout=3)).stuck_execution_ids
        concurrent = get_model_by_model_id(managed_id, "tenant")
        concurrent_profile = restore_runtime_model_snapshot(concurrent, "tenant")
        assert concurrent_profile.config_revision == 4
        assert concurrent_profile.parameter_values["temperature"] == .3
        assert concurrent_profile.parameter_values["top_p"] == .8
        assert concurrent_profile.parameter_rules == captured.parameter_rules
        tampered = deepcopy(concurrent["runtime_outlet_snapshot"])
        tampered["row"]["model_id"] += 1000
        with engine.begin() as connection:
            connection.execute(ModelRecord.__table__.update().where(ModelRecord.model_id == managed_id)
                               .values(runtime_outlet_snapshot=tampered))
        with pytest.raises(ValueError, match="IDENTITY_MISMATCH"):
            restore_runtime_model_snapshot(get_model_by_model_id(managed_id, "tenant"), "tenant")
        with engine.begin() as connection:
            connection.execute(ModelRecord.__table__.update().where(ModelRecord.model_id == managed_id)
                               .values(runtime_outlet_snapshot=concurrent["runtime_outlet_snapshot"]))

        def broken(_row):
            raise ValueError("Controlled provisioning failure")

        with pytest.raises(ValueError, match="Controlled provisioning failure"):
            create_legacy({**data, "display_name": "must-rollback"}, "actor", "tenant",
                          runtime_profile_builder=broken)
        with pytest.raises(ValueError, match="Controlled provisioning failure"):
            update_legacy(managed_id, {"temperature": .9}, "actor", "tenant", runtime_profile_builder=broken)
        rolled_back = get_model_by_model_id(managed_id, "tenant")
        assert rolled_back["temperature"] == .3
        assert rolled_back["runtime_outlet_snapshot"] == concurrent["runtime_outlet_snapshot"]
        with engine.connect() as connection:
            assert connection.execute(select(ModelRecord.model_id)
                .where(ModelRecord.display_name == "must-rollback")).first() is None
        with engine.begin() as connection:
            connection.execute(text("UPDATE nexent.model_record_t SET temperature=.5 WHERE model_id=:id"),
                               {"id": managed_id})
        with pytest.raises(ValueError, match="STALE_SNAPSHOT"):
            restore_runtime_model_snapshot(get_model_by_model_id(managed_id, "tenant"), "tenant")
        # Management repair restores executable state at the next revision.
        assert update_model_record(managed_id, {"temperature": .5}, "actor", "tenant")
        assert restore_runtime_model_snapshot(get_model_by_model_id(managed_id, "tenant"), "tenant").config_revision == 5
    finally:
        if engine is not None:
            engine.dispose()
        docker("rm", "-f", name)

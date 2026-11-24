# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Real PostgreSQL/Redis integration for system configuration."""

import json
import os
import select
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import psycopg2
import pytest
import redis
from infrastructure.system_configuration.catalog import DEFAULT_CATALOG, ConfigurationValidationError
from infrastructure.system_configuration.repository import SystemConfigurationRepository
from infrastructure.system_configuration.runtime import CONFIGURATION_CHANNEL
from psycopg2.extensions import parse_dsn
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

DATABASE_URL = os.environ["NEXENT_SYSTEM_CONFIG_TEST_DATABASE_URL"]
REDIS_URL = os.environ["NEXENT_SYSTEM_CONFIG_TEST_REDIS_URL"]
MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "deploy/sql/migrations/v2.9.0_009_system_configuration.sql"
)
DENYLIST_MIGRATION = MIGRATION.with_name("v2.9.0_014_nl2agent_resource_denylist.sql")


def _engine():
    return create_engine(DATABASE_URL, hide_parameters=True, pool_pre_ping=True)


def _apply_migration(extra_sql=""):
    connection = psycopg2.connect(DATABASE_URL)
    try:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute("\n".join([
                MIGRATION.read_text(encoding="utf-8"),
                DENYLIST_MIGRATION.read_text(encoding="utf-8"),
                extra_sql,
            ]))
    finally:
        connection.close()


def _restore_defaults(engine):
    with engine.begin() as connection:
        for key, value in DEFAULT_CATALOG.defaults.items():
            connection.execute(
                text(
                    "UPDATE nexent.sys_configuration_t "
                    "SET configuration_value = CAST(:value AS jsonb), updated_by = 'system', update_time = CURRENT_TIMESTAMP "
                    "WHERE configuration_key = :key AND delete_flag = 'N'"
                ),
                {"key": key, "value": json.dumps(value)},
            )


def _save_values(engine, changes):
    with Session(engine) as session:
        SystemConfigurationRepository().save_changes(session, changes, actor="ops-user")
        session.commit()


def _worker_diagnostics(worker):
    process = worker["process"]
    worker["stderr"].flush()
    worker["stderr"].seek(0)
    return f"exit={process.poll()}\n{worker['stderr'].read()}"


def _read_worker_message(worker, timeout=20):
    process = worker["process"]
    readable, _, _ = select.select([process.stdout], [], [], timeout)
    if not readable:
        raise AssertionError(_worker_diagnostics(worker))
    line = process.stdout.readline()
    if not line:
        raise AssertionError(_worker_diagnostics(worker))
    message = json.loads(line)
    if message.get("type") == "error":
        raise AssertionError(f"{message['message']}\n{_worker_diagnostics(worker)}")
    return message


def _worker_request(worker, command, timeout=20):
    process = worker["process"]
    process.stdin.write(json.dumps({"type": command}) + "\n")
    process.stdin.flush()
    return _read_worker_message(worker, timeout)


def _start_worker(service):
    repository_root = Path(__file__).resolve().parents[3]
    environment = os.environ.copy()
    python_path = [str(repository_root / "backend"), str(repository_root)]
    if environment.get("PYTHONPATH"):
        python_path.append(environment["PYTHONPATH"])
    environment["PYTHONPATH"] = os.pathsep.join(python_path)
    # The log stays open until the owned worker is reaped in the fixture cleanup.
    stderr = tempfile.TemporaryFile(mode="w+t", encoding="utf-8")  # noqa: SIM115
    process = subprocess.Popen(
        [
            sys.executable,
            str(
                repository_root / "test-e2e/infra/automation/system_config_consumer.py"
            ),
            service,
        ],
        cwd=repository_root,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=stderr,
        text=True,
        bufsize=1,
    )
    worker = {"process": process, "stderr": stderr}
    try:
        ready = _read_worker_message(worker)
    except Exception:
        process.terminate()
        process.wait(timeout=5)
        process.stdin.close()
        process.stdout.close()
        stderr.close()
        raise
    assert ready["type"] == "ready"
    assert ready["service"] == service
    worker["pid"] = ready["pid"]
    return worker


@contextmanager
def _running_consumers():
    workers = {}
    try:
        for service in ("config", "runtime", "northbound"):
            workers[service] = _start_worker(service)
        assert len({worker["pid"] for worker in workers.values()}) == 3
        yield workers
    finally:
        for worker in workers.values():
            process = worker["process"]
            if process.poll() is None:
                try:
                    _worker_request(worker, "stop", timeout=2)
                    process.wait(timeout=5)
                except (
                    AssertionError,
                    OSError,
                    subprocess.SubprocessError,
                    json.JSONDecodeError,
                ):
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
            assert process.poll() is not None, _worker_diagnostics(worker)
            process.stdin.close()
            process.stdout.close()
            worker["stderr"].close()


def _wait_for_consumer_value(workers, key, expected):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        values = [
            _worker_request(worker, "snapshot")["values"].get(key)
            for worker in workers.values()
        ]
        if values == [expected] * len(workers):
            return
        time.sleep(0.05)
    raise AssertionError(f"Consumers did not reach {key}={expected}: {values}")


@pytest.fixture(autouse=True)
def clean_values():
    engine = _engine()
    _apply_migration()
    _restore_defaults(engine)
    try:
        yield
    finally:
        _apply_migration()
        _restore_defaults(engine)
        engine.dispose()


@pytest.mark.case_id("SYS-CONFIG-HOT-REFRESH-D3-001")
@pytest.mark.stage("D3")
def test_repeat_and_concurrent_migration_preserve_user_values():
    engine = _engine()
    previous_environment = os.environ.get("MAX_TENANT_COUNT")
    os.environ["MAX_TENANT_COUNT"] = "3"
    try:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM nexent.sys_configuration_t"))
        _apply_migration()
    finally:
        if previous_environment is None:
            os.environ.pop("MAX_TENANT_COUNT", None)
        else:
            os.environ["MAX_TENANT_COUNT"] = previous_environment

    with engine.connect() as connection:
        count, tenant_limit = connection.execute(
            text(
                "SELECT count(*), (SELECT configuration_value "
                "FROM nexent.sys_configuration_t "
                "WHERE configuration_key = 'MAX_TENANT_COUNT' "
                "AND delete_flag = 'N' LIMIT 1) "
                "FROM nexent.sys_configuration_t WHERE delete_flag = 'N'"
            )
        ).one()
    assert (count, tenant_limit) == (20, 100)
    with Session(engine) as session:
        assert SystemConfigurationRepository().load_snapshot(session).get("NL2AGENT_RESOURCE_DENYLIST") == ()

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM nexent.sys_configuration_t"))
    with pytest.raises(psycopg2.Error):
        _apply_migration(
            "\nINSERT INTO nexent.sys_configuration_t (configuration_key) VALUES (NULL);\n"
        )
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM nexent.sys_configuration_t")
            ).scalar_one()
            == 0
        )
    _apply_migration()

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE nexent.sys_configuration_t SET configuration_value = to_jsonb(5), "
                "updated_by = 'ops-user' WHERE configuration_key = 'MAX_TENANT_COUNT'"
            )
        )
        connection.execute(
            text(
                "DELETE FROM nexent.sys_configuration_t "
                "WHERE configuration_key = 'MAX_SKILL_UPLOAD_SIZE_MB'"
            )
        )

    denylist_key = "NL2AGENT_RESOURCE_DENYLIST"
    _save_values(engine, {denylist_key: ["tool:7"]})
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _: _apply_migration(), range(2)))
    with Session(engine) as session:
        assert SystemConfigurationRepository().load_snapshot(session).get(denylist_key) == ("tool:7",)

    with engine.connect() as connection:
        count, distinct_count = connection.execute(
            text(
                "SELECT count(*), count(DISTINCT configuration_key) FROM nexent.sys_configuration_t WHERE delete_flag = 'N'"
            )
        ).one()
        tenant_limit = connection.execute(
            text(
                "SELECT configuration_value FROM nexent.sys_configuration_t WHERE configuration_key = 'MAX_TENANT_COUNT'"
            )
        ).scalar_one()
        skill_limit = connection.execute(
            text(
                "SELECT configuration_value FROM nexent.sys_configuration_t WHERE configuration_key = 'MAX_SKILL_UPLOAD_SIZE_MB'"
            )
        ).scalar_one()
        actor = connection.execute(
            text(
                "SELECT updated_by FROM nexent.sys_configuration_t WHERE configuration_key = 'MAX_TENANT_COUNT'"
            )
        ).scalar_one()

    assert (count, distinct_count) == (20, 20)
    assert tenant_limit == 5
    assert skill_limit == 10
    assert actor == "ops-user"


@pytest.mark.case_id("SYS-CONFIG-HOT-REFRESH-D3-001")
@pytest.mark.stage("D3")
def test_locked_batch_writes_and_read_only_consumer_role():
    engine = _engine()
    repository = SystemConfigurationRepository()

    barrier = threading.Barrier(2)
    commit_order = []
    order_lock = threading.Lock()

    def save(key, value, *, concurrent=False):
        if concurrent:
            barrier.wait()
        with Session(engine) as session:
            repository.save_changes(session, {key: value}, actor="ops-user")
            session.commit()
        with order_lock:
            commit_order.append((key, value))

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(
            executor.map(
                lambda item: save(*item, concurrent=True),
                [("MAX_TENANT_COUNT", 6), ("MAX_USERS_PER_TENANT", 7)],
            )
        )
    with Session(engine) as session:
        snapshot = repository.load_snapshot(session)
        assert snapshot.get("MAX_TENANT_COUNT") == 6
        assert snapshot.get("MAX_USERS_PER_TENANT") == 7

    barrier = threading.Barrier(2)
    commit_order.clear()
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(
            executor.map(
                lambda value: save("MAX_TENANT_COUNT", value, concurrent=True),
                [8, 9],
            )
        )
    with Session(engine) as session:
        snapshot = repository.load_snapshot(session)
        assert snapshot.get("MAX_TENANT_COUNT") == commit_order[-1][1]
    save("MAX_TENANT_COUNT", 9)
    save("MAX_TENANT_COUNT", 9)

    with pytest.raises(ConfigurationValidationError):
        save("MAX_USERS_PER_TENANT", 0)

    with Session(engine) as session:
        snapshot = repository.load_snapshot(session)
        assert snapshot.get("MAX_TENANT_COUNT") == commit_order[-1][1]
        assert snapshot.get("MAX_USERS_PER_TENANT") == 7

    session = Session(engine)
    original_execute = session.execute
    update_count = 0

    def fail_second_update(statement, *args, **kwargs):
        nonlocal update_count
        if str(statement).lstrip().upper().startswith("UPDATE"):
            update_count += 1
            if update_count == 2:
                raise RuntimeError("injected mid-batch failure")
        return original_execute(statement, *args, **kwargs)

    session.execute = fail_second_update
    with pytest.raises(RuntimeError, match="injected mid-batch failure"):
        repository.save_changes(
            session,
            {"MAX_TENANT_COUNT": 20, "MAX_USERS_PER_TENANT": 21},
            actor="ops-user",
        )
        session.commit()
    session.rollback()
    session.close()

    with Session(engine) as session:
        snapshot = repository.load_snapshot(session)
        assert snapshot.get("MAX_TENANT_COUNT") != 20
        assert snapshot.get("MAX_USERS_PER_TENANT") == 7

    with Session(engine) as session:
        session.execute(text("SET LOCAL ROLE nexent_configuration_reader"))
        session.execute(
            text("SELECT count(*) FROM nexent.sys_configuration_t")
        ).scalar_one()
        with pytest.raises(ProgrammingError, match="permission denied"):
            session.execute(
                text(
                    "UPDATE nexent.sys_configuration_t SET configuration_value = to_jsonb(1) WHERE configuration_key = 'MAX_TENANT_COUNT'"
                )
            )
        session.rollback()


@pytest.mark.case_id("SYS-CONFIG-HOT-REFRESH-D3-001")
@pytest.mark.stage("D3")
def test_independent_consumers_reconcile_duplicate_and_invalid_notifications():
    engine = _engine()
    publisher = redis.Redis.from_url(REDIS_URL)
    try:
        with _running_consumers() as workers:
            key = "NL2AGENT_RESOURCE_DENYLIST"
            _save_values(engine, {key: ["tool:7"]})
            publisher.publish(CONFIGURATION_CHANNEL, "configuration_changed")
            _wait_for_consumer_value(workers, key, ["tool:7"])
            _save_values(engine, {key: []})
            _wait_for_consumer_value(workers, key, [])

            # Direct commits prove consumers do not depend on an ops process.
            _save_values(engine, {"MAX_TENANT_COUNT": 10})
            _wait_for_consumer_value(workers, "MAX_TENANT_COUNT", 10)

            publisher.publish(CONFIGURATION_CHANNEL, "stale-values-and-revision")
            publisher.publish(CONFIGURATION_CHANNEL, "duplicate")
            _save_values(engine, {"MAX_TENANT_COUNT": 11})
            publisher.publish(CONFIGURATION_CHANNEL, "configuration_changed")
            _wait_for_consumer_value(workers, "MAX_TENANT_COUNT", 11)

            publisher.execute_command("CLIENT", "KILL", "TYPE", "pubsub")
            _save_values(engine, {"MAX_TENANT_COUNT": 12})
            _wait_for_consumer_value(workers, "MAX_TENANT_COUNT", 12)

            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE nexent.sys_configuration_t "
                        "SET configuration_value = to_jsonb(0) "
                        "WHERE configuration_key = 'MAX_TENANT_COUNT'"
                    )
                )
            time.sleep(0.2)
            for worker in workers.values():
                values = _worker_request(worker, "snapshot")["values"]
                assert values["MAX_TENANT_COUNT"] == 12

            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE nexent.sys_configuration_t "
                        "SET configuration_value = to_jsonb(13) "
                        "WHERE configuration_key = 'MAX_TENANT_COUNT'"
                    )
                )
            _wait_for_consumer_value(workers, "MAX_TENANT_COUNT", 13)

            with engine.begin() as connection:
                connection.execute(
                    text(
                        "REVOKE SELECT ON nexent.sys_configuration_t "
                        "FROM nexent_configuration_reader"
                    )
                )
            try:
                _save_values(engine, {"MAX_TENANT_COUNT": 14})
                time.sleep(0.2)
                for worker in workers.values():
                    values = _worker_request(worker, "snapshot")["values"]
                    assert values["MAX_TENANT_COUNT"] == 13
            finally:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "GRANT SELECT ON nexent.sys_configuration_t "
                            "TO nexent_configuration_reader"
                        )
                    )
            _wait_for_consumer_value(workers, "MAX_TENANT_COUNT", 14)
    finally:
        publisher.close()


@pytest.mark.case_id("SYS-CONFIG-HOT-REFRESH-D3-001")
@pytest.mark.stage("D3")
def test_subsequent_business_checks_use_refreshed_snapshot():
    engine = _engine()
    with _running_consumers() as workers:
        initial_run = _worker_request(workers["runtime"], "business")["values"]
        assert initial_run == {
            "mcp_request_timeout_seconds": 10,
            "mcp_tool_timeout_seconds": 60,
            "parallel_timeout_seconds": 120,
        }

        _save_values(
            engine,
            {
                "MAX_USERS_PER_TENANT": 1,
                "MAX_EVALUATION_SET_FILE_SIZE_MB": 1,
                "MAX_CONVERSATIONS_PER_USER": 1,
                "MCP_REQUEST_TIMEOUT_SECONDS": 17,
                "RUNTIME_MCP_TOOL_TIMEOUT_SECONDS": 23,
                "RUNTIME_PARALLEL_EXECUTOR_TIMEOUT_SECONDS": 0.25,
            },
        )
        _wait_for_consumer_value(workers, "MCP_REQUEST_TIMEOUT_SECONDS", 17)

        config = _worker_request(workers["config"], "business")["values"]
        assert config == {
            "tenant_limit": 1,
            "limit_mb": 1,
            "limit_bytes": 1024 * 1024,
            "existing_count": 1,
        }
        northbound = _worker_request(workers["northbound"], "business")["values"]
        assert northbound == {"conversation_limit": 1, "existing_count": 1}
        refreshed_run = _worker_request(workers["runtime"], "business")["values"]
        assert refreshed_run == {
            "mcp_request_timeout_seconds": 17,
            "mcp_tool_timeout_seconds": 23,
            "parallel_timeout_seconds": 0.25,
        }
        assert initial_run == {
            "mcp_request_timeout_seconds": 10,
            "mcp_tool_timeout_seconds": 60,
            "parallel_timeout_seconds": 120,
        }


@pytest.mark.case_id("SYS-CONFIG-HOT-REFRESH-D3-001")
@pytest.mark.stage("D3")
@pytest.mark.asyncio
async def test_database_lock_timeout_preserves_snapshot_and_recovers(monkeypatch):
    from infrastructure.system_configuration import database as database_module
    from infrastructure.system_configuration.database import ConfigurationDatabase
    from infrastructure.system_configuration.runtime import SystemConfigurationRuntime

    parameters = parse_dsn(DATABASE_URL)
    for name, value in {
        "POSTGRES_HOST": parameters["host"],
        "POSTGRES_PORT": parameters["port"],
        "POSTGRES_USER": parameters["user"],
        "POSTGRES_DB": parameters["dbname"],
        "NEXENT_POSTGRES_PASSWORD": parameters.get("password"),
    }.items():
        monkeypatch.setattr(database_module, name, value)

    database = ConfigurationDatabase()
    repository = SystemConfigurationRepository()

    async def loader():
        with database.session() as session:
            return repository.load_snapshot(session, read_only=True).values

    runtime = SystemConfigurationRuntime(loader=loader)
    lock_connection = psycopg2.connect(DATABASE_URL)
    try:
        assert await runtime.refresh() is True
        with lock_connection.cursor() as cursor:
            cursor.execute(
                "LOCK TABLE nexent.sys_configuration_t IN ACCESS EXCLUSIVE MODE"
            )

        started = time.monotonic()
        assert await runtime.refresh() is False
        elapsed = time.monotonic() - started
        assert 4 <= elapsed < 15
        assert runtime.get_snapshot().to_dict() == DEFAULT_CATALOG.defaults

        lock_connection.rollback()
        assert await runtime.refresh() is True
    finally:
        lock_connection.rollback()
        lock_connection.close()
        database.dispose()

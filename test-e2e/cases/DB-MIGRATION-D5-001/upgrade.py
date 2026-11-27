# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Rehearse the actual SQL upgrade from a seeded release database."""

from contextlib import contextmanager
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import time
from uuid import uuid4

from shared.asset_registry import AssetDependencyError


SOURCE_VERSION = "v2.8.5"
SOURCE_SHA = "628b53d66c875094eb6fa1ed3b2dff6590bad9e5"
POSTGRES_IMAGE = "postgres:15-alpine"
WORKER_IMAGE = "nexent/nexent-management:latest"
ROWS = 1_000_000
BUDGET = 300
FAMILY = "d5-db-migration"
PROBE_TITLE = "Daily million-row upgrade"
SQL_ROOT = Path("deploy/sql")
COMMON = Path("deploy/common")
READ_WRITE_PROBE = """
from sqlalchemy import select
from infrastructure.rdb.client import get_db_session
from infrastructure.rdb.conversation_record import ConversationRecord

with get_db_session() as session:
    first = session.scalars(select(ConversationRecord).where(
        ConversationRecord.conversation_title == "Daily million-row upgrade"
    ).limit(1)).one()
    assert first.target.get("type") == "agent" and first.target.get("id") > 0
    item = ConversationRecord(conversation_title="Daily upgrade write check", created_by="daily-migration-reader",
                              updated_by="daily-migration-reader", delete_flag="N")
    session.add(item)
    session.flush()
    identifier = item.conversation_id
with get_db_session() as session:
    item = session.get(ConversationRecord, identifier)
    assert item.conversation_title == "Daily upgrade write check"
    session.delete(item)
"""


def command(*args, timeout=45, data=None, output=None, env=None):
    result = subprocess.run(
        ["docker", *args], input=data, stdout=output or subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=timeout, env=env,
    )
    if result.returncode:
        # The Docker environment contains only a generated credential, and the
        # assertion never reflects raw subprocess output into reports.
        raise AssertionError(f"Docker {args[0]} failed with exit {result.returncode}")
    return result.stdout


def local_image(image):
    try:
        return command("image", "inspect", "--format", "{{.Id}}", image).decode().strip()
    except (AssertionError, OSError, subprocess.SubprocessError) as exc:
        raise AssetDependencyError("images", image, detail="Required local test image unavailable") from exc


class Deadline:
    def __init__(self, seconds):
        self.seconds = seconds
        self.started = time.monotonic()

    def remaining(self):
        seconds = self.seconds - self.elapsed()
        if seconds <= 0:
            raise TimeoutError("Upgrade deadline exhausted")
        return seconds

    def elapsed(self):
        return time.monotonic() - self.started


@contextmanager
def stack(postgres_image, management_image):
    name = FAMILY + "-" + uuid4().hex[:16]
    db, worker = name + "-db", name + "-worker"
    label = FAMILY + "=" + name
    pw = uuid4().hex
    env = {**os.environ, "POSTGRES_PASSWORD": pw, "NEXENT_POSTGRES_PASSWORD": pw}
    cleanup = []
    try:
        command("network", "create", "--internal", "--label", label, name)
        cleanup.append(("network", "rm", name))
        command("volume", "create", "--label", label, name)
        cleanup.append(("volume", "rm", name))
        cleanup.append(("rm", "-f", db))
        command("run", "-d", "--name", db, "--network", name, "--label", label,
                "--mount", f"type=volume,source={name},target=/var/lib/postgresql/data",
                "-e", "POSTGRES_USER=root", "-e", "POSTGRES_DB=nexent", "-e", "POSTGRES_PASSWORD",
                postgres_image, env=env)
        cleanup.append(("rm", "-f", worker))
        command("run", "-d", "--name", worker, "--network", name, "--label", label,
                "--entrypoint", "sleep", management_image, "infinity")
        start = Deadline(60)
        while True:
            try:
                command("exec", db, "pg_isready", "-h", "127.0.0.1", "-U", "root", "-d", "nexent",
                        timeout=min(5, start.remaining()))
                break
            except (AssertionError, subprocess.TimeoutExpired):
                time.sleep(0.5)
        yield db, worker, env
    finally:
        errors = []
        for entry in reversed(cleanup):
            try:
                command(*entry, timeout=25)
            except (AssertionError, OSError, subprocess.SubprocessError):
                errors.append(entry[-1])
        assert not errors, "Failed to clean owned migration resources: " + ", ".join(errors)


def sql(db, statement, *, timeout=45, database="nexent"):
    # Only docker-exec into the owned database name returned by stack().
    assert re.fullmatch(FAMILY + r"-[a-f0-9]{16}-db", db), "Unexpected database target"
    return command("exec", "-i", db, "psql", "-X", "-Atq", "-v", "ON_ERROR_STOP=1",
                   "-U", "root", "-d", database, timeout=timeout, data=statement.encode()).decode().strip()


def migration_files(repo, revision=None):
    scripts = [SQL_ROOT / "init.sql", COMMON / "run-sql-migrations.sh"]
    if revision:
        listing = subprocess.check_output(
            ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", revision, str(SQL_ROOT.as_posix())]
        ).decode().splitlines()
        paths = [Path(value) for value in listing if value.startswith("deploy/sql/migrations/") and value.endswith(".sql")]
        return {p.relative_to("deploy").as_posix(): subprocess.check_output(
            ["git", "-C", str(repo), "show", f"{revision}:{p.as_posix()}"]) for p in [*scripts, *paths]}
    paths = list((repo / SQL_ROOT / "migrations").glob("*.sql"))
    paths += list((repo / SQL_ROOT / "migrations" / "ops").glob("*.sql"))
    scripts += [SQL_ROOT / "ops-init.sql", COMMON / "run-ops-sql-migrations.sh"]
    return {p.relative_to("deploy").as_posix(): (repo / p).read_bytes() for p in
            [*scripts, *(item.relative_to(repo) for item in paths)]}


def copy_tree(worker, target, files):
    command("exec", worker, "mkdir", "-p", target)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as archive:
        for path, content in sorted(files.items()):
            item = tarfile.TarInfo(path)
            item.mode = 0o644
            item.size = len(content)
            archive.addfile(item, io.BytesIO(content))
    command("cp", "-", f"{worker}:{target}", data=buf.getvalue(), timeout=60)


def worker_env(db):
    return ("-e", f"POSTGRES_HOST={db}", "-e", "POSTGRES_USER=root",
            "-e", "POSTGRES_DB=nexent", "-e", "NEXENT_POSTGRES_PASSWORD")


def migrate(db, worker, env, prefix, version, output, timeout, *, ops=False, timing=False):
    script = "run-ops-sql-migrations.sh" if ops else "run-sql-migrations.sh"
    args = ("exec", *worker_env(db), "-e", f"NEXENT_APP_VERSION={version}",
            "-e", f"NEXENT_SQL_INIT_FILE={prefix}/sql/init.sql",
            "-e", f"NEXENT_SQL_MIGRATION_DIR={prefix}/sql/migrations",
            "-e", f"NEXENT_SQL_MIGRATION_TIMING={str(timing).lower()}", worker,
            "bash", f"{prefix}/common/{script}", "--migrate")
    with output.open("wb") as log:
        command(*args, output=log, timeout=timeout, env=env)


def seed(repo, db, worker, env, evidence, cache):
    # Restored dumps come from this exact release, row generator and image.
    if cache.is_file():
        with cache.open("rb") as dump:
            result = subprocess.run(
                ["docker", "exec", "-i", db, "pg_restore", "--exit-on-error", "-U", "root", "-d", "nexent"],
                stdin=dump, capture_output=True, timeout=210,
            )
        assert result.returncode == 0, "Restore of the synthetic release snapshot failed"
        return
    prefix = "/tmp/source-release"
    copy_tree(worker, prefix, migration_files(repo, SOURCE_SHA))
    migrate(db, worker, env, prefix, SOURCE_VERSION, evidence / "source-migration.log", 150)
    # These rows are actually selected and rewritten by the creator-target
    # migration, instead of just making an unrelated table large.
    sql(db, f"""
    INSERT INTO nexent.conversation_record_t (conversation_title, agent_id, created_by, updated_by, workbench_config)
    SELECT '{PROBE_TITLE}', 800000 + i % 31, 'daily-owner-' || i % 1000, 'daily-owner-' || i % 1000,
           jsonb_build_object('mode', 'agent_create')
    FROM generate_series(1, {ROWS}) i;
    ANALYZE nexent.conversation_record_t;
    """, timeout=180)
    cache.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=cache.parent, prefix="dump-", delete=False) as dump:
        temporary = Path(dump.name)
    try:
        with temporary.open("wb") as dump:
            command("exec", db, "pg_dump", "-Fc", "-U", "root", "-d", "nexent",
                    output=dump, timeout=200)
        os.replace(temporary, cache)
    finally:
        temporary.unlink(missing_ok=True)


def migration_receipt(log_file):
    details = {}
    for line in log_file.read_text(encoding="utf-8", errors="replace").splitlines():
        status = re.fullmatch(r"\[sql-migrations\] (apply|reapply|skip) (\S+\.sql)", line)
        timing = re.fullmatch(r"\[sql-migrations\] timing (\S+\.sql) (\d+)", line)
        if status:
            action, name = status.groups()
            if name != "__init.sql":
                details[name] = {"action": action}
        if timing:
            name, elapsed = timing.groups()
            details.setdefault(name, {})["elapsed_ms"] = int(elapsed)
    return details


def ledger(db, schema, database, remaining):
    rows = sql(db, f"SELECT migration_id, checksum, status FROM {schema}.schema_migrations",
               database=database, timeout=remaining).splitlines()
    return {name: (digest, status) for name, digest, status in (line.split("|") for line in rows)}


def check_catalog(expected, actual, actions, previous):
    assert set(actions) == set(expected), "Formal migrator did not account for every manifest entry"
    for name, checksum in expected.items():
        assert actual.get(name) in {(checksum, "applied"), (checksum, "baselined")}, f"Bad ledger for {name}"
        if actions[name]["action"] == "skip":
            assert previous.get(name) == actual[name], f"Unexpected skip for {name}"
        assert "elapsed_ms" in actions[name], f"Missing completion timing for {name}"


def exercise(repo, test_home, evidence):
    release = subprocess.run(["git", "-C", str(repo), "cat-file", "-e", SOURCE_SHA + "^{commit}"],
                             capture_output=True, check=False)
    if release.returncode:
        raise AssetDependencyError("git", SOURCE_VERSION, detail="Pinned release commit is missing locally")
    pg_image = local_image(POSTGRES_IMAGE)
    worker_image = local_image(WORKER_IMAGE)
    fixture_digest = sha256(Path(__file__).read_bytes() + pg_image.encode()).hexdigest()[:24]
    cache = test_home / "runtime" / "migration-fixtures" / f"{SOURCE_VERSION}-{fixture_digest}.dump"
    evidence.mkdir(parents=True, exist_ok=True)
    result = {"source": SOURCE_VERSION, "source_sha": SOURCE_SHA, "rows": ROWS,
              "budget_seconds": BUDGET, "postgres_image": pg_image, "worker_image": worker_image}
    logs = {name: evidence / f"{name}-migration.log" for name in ("main", "ops")}
    try:
        with stack(pg_image, worker_image) as (db, worker, env):
            phase_start = time.monotonic()
            seed(repo, db, worker, env, evidence, cache)
            result["fixture_seconds"] = round(time.monotonic() - phase_start, 3)
            assert sql(db, f"SELECT count(*) FROM nexent.conversation_record_t WHERE conversation_title='{PROBE_TITLE}'") == str(ROWS)
            previous = ledger(db, "nexent", "nexent", 45)
            current = migration_files(repo)
            manifests = {"main": {}, "ops": {}}
            for name, content in current.items():
                path = Path(name)
                if "migrations" in path.parts:
                    manifests["ops" if path.parent.name == "ops" else "main"][path.name] = sha256(content).hexdigest()
            version = (repo / "VERSION").read_text().strip()
            prefix = "/tmp/target-release"
            copy_tree(worker, prefix, current)
            deadline = Deadline(BUDGET)
            try:
                for name, log in logs.items():
                    migrate(db, worker, env, prefix, version, log, deadline.remaining(), ops=name == "ops", timing=True)
                main = ledger(db, "nexent", "nexent", deadline.remaining())
                ops = ledger(db, "ops", "nexent_ops", deadline.remaining())
                check_catalog(manifests["main"], main, migration_receipt(logs["main"]), previous)
                check_catalog(manifests["ops"], ops, migration_receipt(logs["ops"]), {})
                count, converted = sql(db, f"""
                    SELECT count(*), count(*) FILTER (
                        WHERE target->>'type'='agent' AND (target->>'id')::integer BETWEEN 800000 AND 800030
                    ) FROM nexent.conversation_record_t WHERE conversation_title='{PROBE_TITLE}'
                    """, timeout=deadline.remaining()).split("|")
                assert int(count) == int(converted) == ROWS, "Unexpected seeded or transformed conversation count"
                command("exec", *worker_env(db), worker, "/opt/backend/.venv/bin/python", "-c", READ_WRITE_PROBE,
                        timeout=deadline.remaining(), env=env)
                deadline.remaining()
                result["converted_rows"] = int(converted)
            except (TimeoutError, subprocess.TimeoutExpired):
                raise AssertionError("Complete database upgrade exceeded 300 seconds") from None
            finally:
                result["upgrade_seconds"] = round(deadline.elapsed(), 3)

            replay = Deadline(90)
            for name in logs:
                migrate(db, worker, env, prefix, version, evidence / f"{name}-replay.log",
                        replay.remaining(), ops=name == "ops", timing=True)
            assert ledger(db, "nexent", "nexent", replay.remaining()) == main, "Business ledger changed on replay"
            assert ledger(db, "ops", "nexent_ops", replay.remaining()) == ops, "Ops ledger changed on replay"
            assert sql(db, f"SELECT count(*) FROM nexent.conversation_record_t WHERE conversation_title='{PROBE_TITLE}'",
                       timeout=replay.remaining()) == str(ROWS), "Migration replay changed fixture data"
            result["replay_seconds"] = round(replay.elapsed(), 3)
    finally:
        result["scripts"] = {name: migration_receipt(log) for name, log in logs.items() if log.is_file()}
        (evidence / "upgrade-metrics.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

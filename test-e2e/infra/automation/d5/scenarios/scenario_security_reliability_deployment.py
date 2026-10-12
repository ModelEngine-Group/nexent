"""D5 main security, reliability and deployment smoke scenarios."""

from __future__ import annotations
import asyncio
import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import pytest
import yaml

from d3.assets import model_id, temporary_conversation, temporary_knowledge_base
from d5.assets import asset_path, destructive_deployment_enabled, require_command, run_command, get_test_asset
from shared.cases import case_params
from shared.config import repo_root
from shared.http import assert_no_server_error, assert_status, client, config_save_payload
from shared.asset_registry import register_asset
from shared.asset_registry import AssetDependencyError
from shared.factories.compose import product_compose_args
from shared.factories.files import _remove_object as _delete_attachment, _upload_attachment
from shared.factories.tenant import isolated_accounts


CASES = ["SEC-001", "SEC-002", "SEC-003", "REL-001", "REL-002", "REL-003", "DEP-001"]


async def _file_acl(owner, attacker, kb_owner) -> None:
    object_name = await _upload_attachment(owner)
    try:
        encoded = quote(object_name, safe="/")
        async with client("config", token=attacker.access_token) as api:
            download = await api.get(f"/file/download/{encoded}", params={"download": "stream"})
            preview = await api.get(f"/file/preview/{encoded}")
            batch = await api.post("/file/storage/batch-urls", json={"object_names": [object_name]})
            deleted = await api.delete(f"/file/storage/{encoded}")
        assert_status(download, 403)
        assert_status(preview, 403)
        assert_status(batch, 200)
        rows = batch.json().get("results") or []
        assert rows and rows[0].get("success") is False and not rows[0].get("url")
        assert_status(deleted, 403)
        async with client("config", token=owner.access_token) as api:
            still_exists = await api.get(f"/file/download/{encoded}", params={"download": "stream"})
        assert_status(still_exists, 200)
    finally:
        await _delete_attachment(owner, object_name)
    # Use a principal allowed to configure KBs; the file ACL still exercises a normal user's ownership.
    embedding_model_id = await model_id("embedding", kb_owner)
    async with temporary_knowledge_base(kb_owner, prefix="d5-acl", embedding_model_id=embedding_model_id) as kb:
        async with client("config", token=attacker.access_token) as api:
            denied = await api.get(f"/indices/{kb['index_name']}/files")
        assert_status(denied, (403, 404))


async def _share_token(identity) -> None:
    async with temporary_conversation(identity, "D5 share") as conversation_id:
        offset_timezone = timezone(timedelta(hours=8))
        async with client("runtime", token=identity.access_token) as api:
            shared = await api.post(
                f"/share/conversation/{conversation_id}",
                json={"mode": "all", "expire_time": (datetime.now(offset_timezone) + timedelta(hours=1)).isoformat(),
                      "render_version": "legacy"},
            )
            expired_share = await api.post(
                f"/share/conversation/{conversation_id}",
                json={"mode": "all", "expire_time": (datetime.now(offset_timezone) - timedelta(hours=1)).isoformat(),
                      "render_version": "legacy"},
            )
        assert_status(shared, 200)
        assert_status(expired_share, 200)
        token = str(shared.json().get("data", {}).get("share_id") or "")
        expired_token = str(expired_share.json().get("data", {}).get("share_id") or "")
        assert token and expired_token and token != expired_token
        register_asset("owned_shares", token, token, owner_case_id="SEC-002", sensitive=True,
                       cleanup={"kind": "revoke_owned_share", "identity": identity.id,
                                "share_token": token})
        register_asset("owned_shares", expired_token, expired_token, owner_case_id="SEC-002", sensitive=True,
                       cleanup={"kind": "revoke_owned_share", "identity": identity.id,
                                "share_token": expired_token})
        async with client("runtime") as public:
            fetched = await public.get(f"/share/{token}")
            expired = await public.get(f"/share/{expired_token}")
            mutated = await public.get(f"/share/{token[:-1]}x")
            missing = await public.get("/share/not-a-valid-token")
        assert_status(fetched, 200)
        assert_status(expired, 404)
        assert_status(mutated, 404)
        assert_status(missing, 404)
        assert "authorization" not in fetched.text.lower()


async def _share_asset() -> None:
    token = str(get_test_asset("sharing", "share_token"))
    asset_id = str(get_test_asset("sharing", "asset_id"))
    other_asset_id = str(get_test_asset("sharing", "unbound_asset_id"))
    base = f"/share/{token}/assets/{asset_id}"
    async with client("runtime") as public:
        download = await public.get(f"{base}/download")
        preview = await public.get(f"{base}/preview")
        partial = await public.get(f"{base}/preview", headers={"Range": "bytes=0-3"})
        invalid_range = await public.get(f"{base}/preview", headers={"Range": "bytes=999999999-"})
        unbound = await public.get(f"/share/{token}/assets/{other_asset_id}/download")
    assert_status(download, 200)
    assert_status(preview, 200)
    assert_status(partial, 206)
    assert_status(invalid_range, 416)
    assert_status(unbound, 404)
    assert download.headers.get("etag") == preview.headers.get("etag")
    assert partial.headers.get("content-range", "").startswith("bytes 0-3/")


async def _runtime_lifecycle(identity) -> None:
    async with client("runtime", token=identity.access_token) as api:
        health = await api.get(
            "/conversation/list",
            params={"today_start_ms": 0, "week_start_ms": 0, "offset": 0, "limit": 1},
        )
    assert_status(health, 200)
    async with client("runtime", token=identity.access_token) as api:
        automations = await api.get("/agent/automations", params={"page": 1, "page_size": 1})
    assert_status(automations, 200)
    source = (repo_root() / "backend" / "apps" / "runtime_app.py").read_text(encoding="utf-8")
    assert "cleanup_orphaned_agent_workspaces()" in source
    assert "await agent_automation_scheduler.start()" in source
    assert "await agent_automation_scheduler.stop()" in source


async def _config_sync(identity) -> None:
    async with client("config", token=identity.access_token) as api:
        before = await api.get("/config/load_config")
        assert_status(before, 200)
        current = before.json().get("config")
        assert isinstance(current, dict) and {"app", "models"}.issubset(current)
        save_payload = config_save_payload(before.json())
        saved = await api.post("/config/save_config", json=save_payload)
        after = await api.get("/config/load_config")
        invalid = await api.post("/config/save_config", json={"app": {}})
    assert_status(saved, 200)
    assert_status(after, 200)
    assert config_save_payload(after.json()) == save_payload
    assert_status(invalid, (400, 422))


async def _config_sync_isolated() -> None:
    async with isolated_accounts(["tenant_a_admin"]) as accounts:
        await _config_sync(accounts["tenant_a_admin"])


async def _workspace_cleanup_contract() -> None:
    source = (repo_root() / "backend" / "services" / "workspace_cleanup_service.py").read_text(encoding="utf-8")
    assert "cleanup_orphaned_agent_workspaces" in source
    assert "_RUN_ID_PATTERN.fullmatch(run_dir.name)" in source
    assert "root.is_symlink()" in source and "run_dir.is_symlink()" in source
    assert "not run_dir.is_dir()" in source
    assert "shutil.rmtree" in source


async def _docker_deployment() -> None:
    destructive_deployment_enabled()
    docker = require_command("docker")
    project = str(get_test_asset("deployment", "compose_project"))
    base = product_compose_args(project)
    code, output = await run_command(docker, *base, "config", "--quiet")
    assert code == 0, output
    code, output = await run_command(docker, *base, "up", "-d", "--wait", timeout=1800)
    assert code == 0, output
    code, output = await run_command(docker, *base, "ps", "--format", "json")
    assert code == 0 and "unhealthy" not in output.lower() and "exited" not in output.lower(), output


async def _kubernetes_deployment() -> None:
    destructive_deployment_enabled()
    helm = require_command("helm")
    kubectl = require_command("kubectl")
    code, output = await run_command(kubectl, "config", "current-context", timeout=30)
    context = output.strip()
    if code != 0 or not context:
        raise AssetDependencyError(
            "deployment", "kube_context", consumer_case_id="DEP-002",
            detail="No usable current Kubernetes context; configure kubeconfig before deployment testing",
        )
    code, output = await run_command(
        kubectl, "--context", context, "get", "--raw=/readyz", "--request-timeout=10s", timeout=30,
    )
    if code != 0 or output.strip() != "ok":
        raise AssetDependencyError(
            "deployment", "kube_context", consumer_case_id="DEP-002",
            detail="Kubernetes API readiness probe failed; check cluster connectivity and credentials",
        )
    chart = repo_root() / "deploy" / "k8s" / "helm" / "nexent"
    release = str(get_test_asset("deployment", "helm_release"))
    namespace = str(get_test_asset("deployment", "k8s_namespace"))
    values = asset_path("deployment", "helm_values_file")
    # Apply the machine-owned isolated storage/secrets and pin the template
    # namespace as well as Helm's release namespace.
    options = ("-f", str(values), "--set-string", f"global.namespace={namespace}")
    code, output = await run_command(helm, "lint", str(chart), *options)
    assert code == 0, output
    code, output = await run_command(helm, "upgrade", "--install", release, str(chart), "--kube-context", context, "-n", namespace, *options, "--create-namespace", "--wait", timeout=1800)
    assert code == 0, output
    code, output = await run_command(kubectl, "--context", context, "get", "pods,svc,ingress", "-n", namespace, "-o", "json")
    assert code == 0 and '"phase": "Failed"' not in output, output


def _offline_plan_images(output: str) -> list[str]:
    image_ref = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]*:[A-Za-z0-9._-]+")
    images = list(dict.fromkeys(line.strip() for line in output.splitlines()
                                if image_ref.fullmatch(line.strip())))
    assert images, "offline dry-run did not declare any images"
    return images


def _offline_archive_names(images: list[str]) -> set[str]:
    names = set()
    for image in images:
        base = image.rsplit("/", 1)[-1]
        name = base.split(":", 1)[0]
        tag = image.rsplit(":", 1)[-1].replace("RELEASE.", "").replace(".", "-")
        names.add(f"{name}-{tag}.tar")
    assert len(names) == len(images), "offline package image archive names collide"
    return names


def _offline_bash() -> str:
    if os.name != "nt":
        return require_command("bash")
    git = shutil.which("git")
    candidate = Path(git).resolve().parent.parent / "bin" / "bash.exe" if git else None
    if candidate and candidate.is_file():
        return str(candidate)
    pytest.skip("BLOCKED: Git Bash is required for Windows offline packaging")


async def _offline_package() -> None:
    destructive_deployment_enabled()
    bash = _offline_bash()
    docker = require_command("docker")
    script = repo_root() / "deploy" / "offline" / "build_offline_package.sh"
    result_dir = Path(os.environ["RESULT_DIR"]).resolve()
    package = result_dir / "d5" / "offline-package"
    script_arg = script.as_posix() if os.name == "nt" else str(script)
    output_arg = package.as_posix() if os.name == "nt" else str(package)
    options = ("--version", "latest", "--image-source", "local-latest",
               "--image-registry-prefix", "", "--defaults",
               "--output-dir", output_arg, "--compress", "false")
    code, output = await run_command(bash, script_arg, *options, "--dry-run", timeout=120)
    assert code == 0, output
    images = _offline_plan_images(output)
    missing = []
    for image in images:
        inspect_code, _ = await run_command(docker, "image", "inspect", image, timeout=30)
        if inspect_code:
            missing.append(image)
    if missing:
        pytest.skip("BLOCKED: offline package requires local images; no registry pull is allowed: " +
                    ", ".join(missing))

    build_log = result_dir / "logs" / "offline-package.log"
    code, output = await run_command(bash, script_arg, *options, timeout=3600, log_path=build_log)
    assert code == 0, output
    assert "Pulling image:" not in build_log.read_text(encoding="utf-8", errors="replace"), (
        "offline build contacted an image registry; inspect offline-package.log"
    )
    manifest_path = package / "manifest.yaml"
    checksum_path = package / "checksums.txt"
    assert manifest_path.is_file() and checksum_path.is_file(), "offline package lacks manifest or checksums"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    assert manifest.get("version") == "latest" and manifest.get("imageSource") == "local-latest"
    assert not manifest.get("imageRegistryPrefix"), "offline package used a remote registry prefix"
    assert set(manifest.get("images") or []) == set(images), "offline package image inventory differs from plan"
    archives = list((package / "images").glob("*.tar"))
    assert {path.name for path in archives} == _offline_archive_names(images), "offline package image archives missing"
    assert all(path.stat().st_size > 0 for path in archives), "offline package image archive is empty"

    verified = set()
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]{64})  (.+)", line)
        assert match, "invalid offline checksum entry"
        file_path = (package / match.group(2)).resolve()
        assert file_path.is_relative_to(package.resolve()) and file_path.is_file()
        with file_path.open("rb") as source:
            assert hashlib.file_digest(source, "sha256").hexdigest() == match.group(1).lower(), file_path.name
        verified.add(file_path)
    expected_files = {path.resolve() for path in package.rglob("*")
                      if path.is_file() and path != checksum_path}
    assert verified == expected_files, "offline package checksum coverage is incomplete"


async def _migration_idempotency() -> None:
    destructive_deployment_enabled()
    docker = require_command("docker")
    project = str(get_test_asset("deployment", "compose_project"))
    compose = product_compose_args(project)
    command = (
        docker, *compose, "exec", "-T", "nexent-config",
        "/opt/nexent/scripts/run-sql-migrations.sh", "--migrate",
    )
    first_code, first = await run_command(*command, timeout=1800)
    second_code, second = await run_command(*command, timeout=1800)
    assert first_code == 0, first
    assert second_code == 0, second
    assert "error" not in second.lower() or "already" in second.lower()


_MERGED_FILE = "deploy/sql/migrations/v2.5.0_merged_migrations.sql"
_V260_MERGED_FILE = "deploy/sql/migrations/v2.6.0_merged_migrations.sql"
_INIT_FILE = "deploy/sql/init.sql"
_PROBE_FILE = "deploy/sql/migrations/v2.5.0_0806_add_conversation_knowledge_scope.sql"
_PRE_V25_MERGED_FILES = (
    "v1_merged_migrations.sql", "v2.0_merged_migrations.sql",
    "v2.1_merged_migrations.sql", "v2.2_merged_migrations.sql",
    "v2.3_merged_migrations.sql", "v2.4_merged_migrations.sql",
)


async def _git_show(commit: str, path: str) -> str:
    git = require_command("git")
    code, output = await run_command(git, "-C", str(repo_root()), "show", f"{commit}:{path}")
    assert code == 0, f"git show {commit}:{path} failed: {output[-800:]}"
    return output


async def _legacy_source_commit() -> str:
    """Return the commit whose PARENT still carries the pre-merge files."""
    git = require_command("git")
    code, output = await run_command(
        git, "-C", str(repo_root()), "log", "--all", "--format=%H",
        "--diff-filter=D", "--", _PROBE_FILE,
    )
    assert code == 0, output
    deletions = [line for line in output.splitlines() if re.fullmatch(r"[0-9a-f]{40}", line)]
    if not deletions:
        raise AssertionError(
            "cannot locate the commit that merged the pre-v2.5.0 single-file migrations; "
            f"git log output: {output!r}"
        )
    return f"{deletions[0]}^"


def _merged_section_names(merged_sql: str) -> list[str]:
    names = re.findall(r"^-- Source migration: (.+\.sql)$", merged_sql, flags=re.MULTILINE)
    if len(names) < 12:
        raise AssertionError(f"expected >=12 embedded source sections in the merged file, found {names}")
    return names


def _psql_script(database: str, extra: str) -> str:
    safe_db = re.fullmatch(r"[a-z0-9_]+", database)
    if not safe_db:
        raise AssertionError(f"refusing to interpolate unsafe database name {database!r}")
    return (
        'PGOPTIONS="-c search_path=nexent,public" '
        f'PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -U "$POSTGRES_USER" -d {database} {extra}'
    )


async def _pg_exec(base: list[str], database: str, statement: str | None, *, stdin: bytes | None = None, timeout: float = 900) -> str:
    docker = require_command("docker")
    if stdin is not None:
        shell = _psql_script(database, "-v ON_ERROR_STOP=1 -q -f -")
    elif statement:
        shell = _psql_script(database, f'-v ON_ERROR_STOP=1 -Atqc "{statement}"')
    else:
        raise AssertionError("either statement or stdin is required")
    args = [*base, "exec", "-T", "nexent-postgresql", "sh", "-c", shell]
    if stdin is None:
        code, output = await run_command(docker, *args, timeout=timeout)
    else:
        process = await asyncio.create_subprocess_exec(
            docker, *args, cwd=str(repo_root()),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout_data, _ = await asyncio.wait_for(process.communicate(stdin), timeout=timeout)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise AssertionError(f"psql apply timed out after {timeout}s")
        code, output = int(process.returncode or 0), stdout_data.decode("utf-8", errors="replace")
    if code != 0:
        raise AssertionError(f"psql on {database} failed (exit={code}): {output[-1500:]}")
    return output


async def _pg_admin(base: list[str], statement: str) -> None:
    await _pg_exec(base, "postgres", statement)


async def _initialize_pre_v25(base: list[str], database: str) -> None:
    """Build the actual migration predecessor, not only the minimal init.sql."""
    await _pg_exec(base, database, None, stdin=(repo_root() / _INIT_FILE).read_bytes())
    migration_dir = repo_root() / "deploy" / "sql" / "migrations"
    for name in _PRE_V25_MERGED_FILES:
        await _pg_exec(base, database, None, stdin=(migration_dir / name).read_bytes())


async def _pg_state(base: list[str], database: str) -> str:
    chunks = []
    queries = [
        "SELECT table_schema||'.'||table_name FROM information_schema.tables "
        "WHERE table_schema NOT IN ('pg_catalog','information_schema') ORDER BY 1",
        "SELECT table_schema||'.'||table_name||'.'||column_name||':'||data_type FROM information_schema.columns "
        "WHERE table_schema NOT IN ('pg_catalog','information_schema') ORDER BY 1",
        "SELECT grantee||'|'||table_schema||'.'||table_name||'|'||privilege_type "
        "FROM information_schema.role_table_grants ORDER BY 1",
        "SELECT 'role_permissions='||count(*)||'|distinct_ids='||count(DISTINCT role_permission_id) FROM nexent.role_permission_t",
    ]
    for query in queries:
        chunks.append(await _pg_exec(base, database, query))
    return "\n".join(chunks)


async def _merged_migration_equivalence() -> None:
    """Candidate V5 DEP-004 step 8 / the current migration-upgrade case step 7.

    - embedded source SHA-256 annotations match the pre-merge single files;
    - applying v2.5.0_merged_migrations.sql twice on a freshly initialised
      scratch database is idempotent (identical state, no duplicate grants);
    - a legacy scratch database that applied the pre-merge single files
      reaches the identical state when the merged file is layered on top.
    """
    destructive_deployment_enabled()
    docker = require_command("docker")
    project = str(get_test_asset("deployment", "compose_project"))
    base = product_compose_args(project)

    init_sql = (repo_root() / _INIT_FILE).read_bytes()
    merged_sql_text = (repo_root() / _MERGED_FILE).read_text(encoding="utf-8")
    merged_sql = (repo_root() / _MERGED_FILE).read_bytes()

    # (1) The embedded source annotations must match the pre-merge files byte
    # for byte, which is what "equivalent to the sequential single files" means.
    sections = _merged_section_names(merged_sql_text)
    source_commit = await _legacy_source_commit()
    embedded = dict(re.findall(
        r"^-- Source migration: (.+\.sql)\n-- Source SHA-256: ([0-9a-f]{64})$",
        merged_sql_text, flags=re.MULTILINE,
    ))
    assert set(embedded) == set(sections), "every merged section must carry a SHA-256 annotation"
    legacy_files: dict[str, bytes] = {}
    for name in sections:
        body = await _git_show(source_commit, f"deploy/sql/migrations/{name}")
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        assert digest == embedded[name], (
            f"embedded SHA-256 for {name} does not match the pre-merge source file"
        )
        legacy_files[name] = body.encode("utf-8")

    token = uuid.uuid4().hex[:10]
    fresh_db, legacy_db = f"dep004_{token}_fresh", f"dep004_{token}_legacy"
    await _pg_admin(base, f"CREATE DATABASE {fresh_db}")
    await _pg_admin(base, f"CREATE DATABASE {legacy_db}")
    try:
        await _initialize_pre_v25(base, fresh_db)
        await _initialize_pre_v25(base, legacy_db)

        # (2) empty-library idempotency: init + merged twice.
        await _pg_exec(base, fresh_db, None, stdin=merged_sql)
        state_after_first = await _pg_state(base, fresh_db)
        await _pg_exec(base, fresh_db, None, stdin=merged_sql)
        state_after_second = await _pg_state(base, fresh_db)
        assert state_after_first == state_after_second, (
            "second application of the merged v2.5.0 file changed database state"
        )
        assert "role_permissions=" in state_after_second
        counts_line = next(
            line for line in state_after_second.splitlines() if line.startswith("role_permissions=")
        )
        total_part, distinct_part = re.match(r"(role_permissions=\d+)\|(distinct_ids=\d+)", counts_line).groups()
        assert int(total_part.split("=")[1]) == int(distinct_part.split("=")[1]), (
            f"repeated merged application produced duplicate permission rows: {counts_line}"
        )

        # (3) legacy library: pre-merge single files, then the merged file on
        # top must be a conflict-free no-op and converge on the fresh state.
        for name in sections:
            await _pg_exec(base, legacy_db, None, stdin=legacy_files[name])
        legacy_before_overlay = await _pg_state(base, legacy_db)
        await _pg_exec(base, legacy_db, None, stdin=merged_sql)
        legacy_after_overlay = await _pg_state(base, legacy_db)
        assert legacy_before_overlay == legacy_after_overlay, (
            "layering the merged file onto the pre-merge single-file state changed schema/permissions"
        )
        assert legacy_after_overlay == state_after_second, (
            "merged single file and the pre-merge migration sequence must reach an equivalent schema"
        )
    finally:
        for database in (fresh_db, legacy_db):
            await _pg_admin(base, f"DROP DATABASE IF EXISTS {database} WITH (FORCE)")


async def _v260_merged_migration_equivalence() -> None:
    """Prove the v2.6 merge preserves its eight source migrations.

    Both paths start from init + the prior v2.5 merged baseline.  One applies
    the new merged file twice; the other applies the exact pre-merge source
    files and then overlays the merged file.  Schema/permission state must be
    identical and the second merged application must be a no-op.
    """
    destructive_deployment_enabled()
    docker = require_command("docker")
    project = str(get_test_asset("deployment", "compose_project"))
    base = product_compose_args(project)
    init_sql = (repo_root() / _INIT_FILE).read_bytes()
    prior_sql = (repo_root() / _MERGED_FILE).read_bytes()
    merged_path = repo_root() / _V260_MERGED_FILE
    merged_text = merged_path.read_text(encoding="utf-8")
    merged_sql = merged_path.read_bytes()
    sections = re.findall(r"^-- Source migration: (.+\.sql)$", merged_text, flags=re.MULTILINE)
    assert sections == [
        "v2.5.0_0813_conversation_source_search_citation.sql",
        "v2.5.0_0904_external_memory_provider.sql",
        "v2.5.1_001_human_interaction.sql",
        "v2.5.1_upload_owner_service.sql",
        "v2.5.2_unified_tag_management.sql",
        "v2.5.3_database_bootstrap_idempotency.sql",
        "v2.5.4_0910_context_budget_v2.sql",
        "v2.6.0_0806_add_model_inference_params.sql",
    ]
    embedded = dict(re.findall(
        r"^-- Source migration: (.+\.sql)\n-- Source SHA-256: ([0-9a-f]{64})$",
        merged_text, flags=re.MULTILINE,
    ))
    assert set(embedded) == set(sections)

    git = require_command("git")
    probe = f"deploy/sql/migrations/{sections[0]}"
    code, output = await run_command(
        git, "-C", str(repo_root()), "log", "--all", "--format=%H",
        "--diff-filter=D", "--", probe,
    )
    assert code == 0, output
    deletion = next((line for line in output.splitlines() if re.fullmatch(r"[0-9a-f]{40}", line)), "")
    assert deletion, f"cannot locate v2.6 merge deletion for {probe}"
    source_commit = f"{deletion}^"
    legacy_files: dict[str, bytes] = {}
    for name in sections:
        body = await _git_show(source_commit, f"deploy/sql/migrations/{name}")
        assert hashlib.sha256(body.encode("utf-8")).hexdigest() == embedded[name]
        legacy_files[name] = body.encode("utf-8")

    token = uuid.uuid4().hex[:10]
    fresh_db, legacy_db = f"dep260_{token}_fresh", f"dep260_{token}_legacy"
    await _pg_admin(base, f"CREATE DATABASE {fresh_db}")
    await _pg_admin(base, f"CREATE DATABASE {legacy_db}")
    try:
        for database in (fresh_db, legacy_db):
            await _initialize_pre_v25(base, database)
            await _pg_exec(base, database, None, stdin=prior_sql)
        await _pg_exec(base, fresh_db, None, stdin=merged_sql)
        state_once = await _pg_state(base, fresh_db)
        await _pg_exec(base, fresh_db, None, stdin=merged_sql)
        state_twice = await _pg_state(base, fresh_db)
        assert state_once == state_twice, "second v2.6 merged application changed database state"
        for name in sections:
            await _pg_exec(base, legacy_db, None, stdin=legacy_files[name])
        legacy_before = await _pg_state(base, legacy_db)
        await _pg_exec(base, legacy_db, None, stdin=merged_sql)
        legacy_after = await _pg_state(base, legacy_db)
        assert legacy_before == legacy_after, "v2.6 merged overlay changed pre-merge source-file state"
        assert legacy_after == state_twice, "v2.6 merged and source-file paths diverged"
    finally:
        for database in (fresh_db, legacy_db):
            await _pg_admin(base, f"DROP DATABASE IF EXISTS {database} WITH (FORCE)")


@pytest.mark.asyncio
async def execute_d5_main(case, tenant_a_admin, tenant_a_user, tenant_b_user):
    case_id = case["id"]
    if case_id == "SEC-001":
        await _file_acl(tenant_a_user, tenant_b_user, tenant_a_admin)
    elif case_id == "SEC-002":
        await _share_token(tenant_a_user)
    elif case_id == "SEC-003":
        await _share_asset()
    elif case_id == "REL-001":
        await _runtime_lifecycle(tenant_a_user)
    elif case_id == "REL-002":
        await _config_sync_isolated()
    elif case_id == "REL-003":
        await _workspace_cleanup_contract()
    elif case_id == "DEP-001":
        await _docker_deployment()
    elif case_id == "DEP-002":
        await _kubernetes_deployment()
    elif case_id == "DEP-004":
        await _migration_idempotency()
        await _merged_migration_equivalence()
        await _v260_merged_migration_equivalence()
    else:
        raise AssertionError(f"unmapped D5 case {case_id}")

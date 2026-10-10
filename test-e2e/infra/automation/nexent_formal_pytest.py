"""Formal case fixtures and evidence hooks, registered under a unique name."""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from _pytest.outcomes import Failed

from shared.auth import sign_in
from shared.config import load_yaml
from shared.asset_registry import (
    AssetDependencyError,
    AssetTimeoutError,
    AutomationInfrastructureError,
)
from shared.postgres import apply_product_postgres_env
from shared.tag_assets import cleanup_automation_tag_definitions


_LOCK = threading.Lock()

# Exact case policy is shared with the targeted runner, so preparation cannot
# start before a database-specific case is rejected there.
DATABASE_TEST_CASES = frozenset(json.loads(
    (Path(__file__).parent / "database-test-policy.json").read_text(encoding="utf-8")
)["excluded_case_ids"])

# Product config_app registers the AIDP routes conditionally.  The same case
# policy is used by the single-case runner before any asset preparation.
FEATURE_TEST_POLICY = json.loads(
    (Path(__file__).parent / "feature-test-policy.json").read_text(encoding="utf-8")
)


def _dependency_blocks() -> dict[str, str]:
    result_dir = os.environ.get("RESULT_DIR", "").strip()
    if not result_dir:
        return {}
    runtime_dir = Path(result_dir) / "runtime"
    path = runtime_dir / "full-prerequisite-plan.json"
    if not path.is_file():
        return {}
    plan = json.loads(path.read_text(encoding="utf-8"))
    blocked = {case_id: "case-owned prerequisite review is missing"
               for case_id in plan["blocked_case_ids"]}
    for case_id, families in plan.get("case_factory_families", {}).items():
        for family in families:
            status_path = runtime_dir / "factory-status" / f"{family}.exit"
            code = status_path.read_text(encoding="utf-8").strip() if status_path.is_file() else "missing"
            if code != "0":
                blocked[case_id] = f"asset factory {family} failed (exit={code})"
                break
    return blocked


@pytest.fixture(autouse=True)
def isolated_migration_database(request, monkeypatch):
    # Audited callers use shared.postgres for all connections/SQL. Never
    # apply this to imported product singletons or unknown database tests.
    isolated = {'DEP-AUTO-2D0252F1DB402184','DEP-AUTO-6D109C4E590A97BF',
                'DEP-AUTO-8213435EA30EB371','REL-AUTO-DD1A9CB3B544F39F'}
    ids = {str(mark.args[0]) for mark in request.node.iter_markers('case_id') if mark.args}
    if ids & {'REL-AUTO-3CE643378A04EF53', 'API-AUTO-2B3A078E3CD1B151'}:
        from services import redis_service
        from shared.factories.redis_target import deployed_redis_urls
        general, backend = deployed_redis_urls()
        monkeypatch.setattr(redis_service, 'REDIS_URL', general)
        monkeypatch.setattr(redis_service, 'REDIS_BACKEND_URL', backend)
        if 'API-AUTO-2B3A078E3CD1B151' in ids:
            # The fallback assertion imports the real Celery task module, which
            # reads canonical constants rather than redis_service's aliases.
            from consts import const
            monkeypatch.setattr(const, 'REDIS_URL', general)
            monkeypatch.setattr(const, 'REDIS_BACKEND_URL', backend)
        # Single-case processes have no pre-existing service. Refuse to
        # redirect another test's already connected singleton.
        if redis_service._redis_service is not None:
            raise RuntimeError('Redis service was initialized before isolated reliability setup')
    if ids & {'REL-AUTO-4CBD1BF08020ABF9','REL-AUTO-D78B50240E78970B'}:
        from shared.factories.scratch_database import isolated_product_database
        from shared.factories.object_storage import owned_recovery_objects, configured_product_storage
        with isolated_product_database(), configured_product_storage() as storage:
            with owned_recovery_objects(storage):
                yield
        return
    orm_isolated = {'REL-AUTO-58D118DDC12E94CA','REL-AUTO-D7FD61217390A8EE',
                    'REL-AUTO-0420654CDB5C783B','REL-AUTO-0ED11882BC558420',
                    'REL-AUTO-CCF3D3CB5D0FC268','REL-AUTO-DAF6A75DB19AEFBC',
                    'REL-AUTO-DAED0399BC7F3CAB','REL-AUTO-4045B602F3B5254D',
                    'REL-AUTO-3CE643378A04EF53','REL-AUTO-53457E34A331A3FF'}
    if ids & orm_isolated:
        from shared.factories.scratch_database import isolated_product_database
        with isolated_product_database():
            yield
        return
    if not ids & isolated:
        yield
        return
    from shared.factories.scratch_database import isolated_schema_database
    with isolated_schema_database():
        yield


async def _required_identity(identity_id: str):
    try:
        return await sign_in(identity_id)
    except Exception as exc:
        # Authentication is a shared batch prerequisite.  Preserve one root
        # dependency and classify every consumer as blocked instead of turning
        # the same setup outage into dozens of independent product failures.
        raise AssetDependencyError(
            "identities", identity_id,
            dependency_case_id=f"D0-IDENTITY-{identity_id.upper()}",
            detail=f"shared sign-in prerequisite failed: {type(exc).__name__}: {exc}",
        ) from exc


def _redact_reason(value: str) -> str:
    value = re.sub(r"(?i)bearer\s+[a-z0-9._~+/=-]+", "Bearer ***", value)
    value = re.sub(
        r"(?i)(api[_-]?key|access[_-]?key|northbound_admin_key|password|secret|token)(\s*[:=]\s*)['\"]?[^\s,'\"}]+",
        r"\1\2***",
        value,
    )
    value = re.sub(r'\bnexent-[A-Za-z0-9_-]{16,}\b', '[REDACTED_KEY]', value)
    return value


def redact_report(report, fixtures):
    """Scrub credentials before terminal and JUnit reporters persist traceback locals."""
    secrets = []
    for name, value in fixtures.items():
        if isinstance(value, str) and len(value) >= 8 and re.search(r'password|secret|token|key', name, re.I):
            secrets.append(value)
        for key in ('access_token', 'refresh_token', 'password'):
            secret = getattr(value, key, None)
            if isinstance(secret, str) and len(secret) >= 8:
                secrets.append(secret)
    def scrub(text):
        for secret in sorted(set(secrets), key=len, reverse=True):
            text = text.replace(secret, '[REDACTED]')
        return _redact_reason(text)
    if report.longrepr:
        # Keep pytest's skip tuple structure; failed tracebacks can be text.
        if isinstance(report.longrepr, tuple):
            report.longrepr = (*report.longrepr[:2], scrub(str(report.longrepr[2])))
        else:
            report.longrepr = scrub(str(report.longrepr))
    report.sections = [(name, scrub(text)) for name, text in report.sections]


def _database_dependency_failure(value: BaseException | None) -> bool:
    """Recognize connection-level DB prerequisite failures without importing DB drivers."""
    if value is None:
        return False
    type_name = f"{type(value).__module__}.{type(value).__name__}".lower()
    message = str(value).lower()
    driver_error = "operationalerror" in type_name
    connection_signal = any(token in message for token in (
        "connection refused", "could not connect", "connection to server",
        "server closed the connection", "no such file or directory",
    ))
    return driver_error and connection_signal


@pytest_asyncio.fixture(scope="session")
async def tenant_a_admin():
    return await _required_identity("tenant_a_admin")


@pytest_asyncio.fixture(scope="session")
async def super_admin():
    return await _required_identity("super_admin")


@pytest_asyncio.fixture(scope="session")
async def tenant_a_dev():
    return await _required_identity("tenant_a_dev")


@pytest_asyncio.fixture(scope="session")
async def tenant_a_user():
    return await _required_identity("tenant_a_user")


@pytest_asyncio.fixture(scope="session")
async def tenant_b_admin():
    return await _required_identity("tenant_b_admin")


@pytest_asyncio.fixture(scope="session")
async def tenant_b_user():
    return await _required_identity("tenant_b_user")


@pytest_asyncio.fixture
async def tag_asset_guard(tenant_a_admin,request):
    """Keep tag-capacity tests isolated across failures and interrupted runs."""
    owners={str(mark.args[0]) for mark in request.node.iter_markers('case_id') if mark.args}
    await cleanup_automation_tag_definitions(tenant_a_admin.access_token,owner_case_ids=owners)
    try:
        yield
    finally:
        await cleanup_automation_tag_definitions(tenant_a_admin.access_token,owner_case_ids=owners)


@pytest_asyncio.fixture(scope="session")
async def northbound_key(tenant_a_user):
    """Create one isolated northbound API key and always revoke it after the session."""
    from shared.http import assert_status, client

    async with client("config", token=tenant_a_user.access_token) as api:
        created = await api.post("/user/tokens")
        assert_status(created, 200)
        payload = created.json().get("data") or created.json()
        token_id = payload.get("token_id") or payload.get("id")
        secret = payload.get("access_key") or payload.get("token")
        if not token_id or not secret:
            raise AssertionError("token creation did not return token_id and one-time access_key")
    try:
        yield str(secret)
    finally:
        async with client("config", token=tenant_a_user.access_token) as api:
            cleanup = await api.delete(f"/user/tokens/{token_id}")
            assert_status(cleanup, (200, 404))


@pytest_asyncio.fixture(scope="session")
async def northbound_admin_key(tenant_a_admin):
    """Administrative northbound key used by API-user management contracts."""
    from shared.http import assert_status, client

    async with client("config", token=tenant_a_admin.access_token) as api:
        created = await api.post("/user/tokens")
        assert_status(created, 200)
        payload = created.json().get("data") or created.json()
        token_id = payload.get("token_id") or payload.get("id")
        secret = payload.get("access_key") or payload.get("token")
        if not token_id or not secret:
            raise AssertionError("admin token creation did not return token_id and access_key")
    try:
        yield str(secret)
    finally:
        async with client("config", token=tenant_a_admin.access_token) as api:
            cleanup = await api.delete(f"/user/tokens/{token_id}")
            assert_status(cleanup, (200, 404))


def pytest_configure(config: pytest.Config) -> None:
    result_dir = Path(os.environ.get("RESULT_DIR", "")).resolve() if os.environ.get("RESULT_DIR") else None
    config._nexent_result_dir = result_dir  # type: ignore[attr-defined]
    recorded: set[str] = set()
    existing = result_dir / "checkpoints" / "results.jsonl" if result_dir else None
    if existing and existing.is_file():
        for raw in existing.read_text(encoding="utf-8").splitlines():
            try:
                case_id = str(json.loads(raw).get("case_id") or "").strip()
            except (json.JSONDecodeError, AttributeError):
                continue
            if case_id:
                recorded.add(case_id)
    config._nexent_recorded = recorded  # type: ignore[attr-defined]

    planned: dict[str, str] = {}
    plan_path = result_dir / "agent-input" / "execution-plan.json" if result_dir else None
    if plan_path and plan_path.is_file():
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
        for entry in payload.get("items", []):
            entry_id = str(entry.get("id") or "").strip()
            entry_stage = str(entry.get("stage") or "").strip().upper()
            if entry_id:
                planned[entry_id] = entry_stage
    config._nexent_planned = planned  # type: ignore[attr-defined]

    # Product DB modules resolve POSTGRES_* constants during test-module
    # import.  Populate the shared deployed-container target before collection
    # so D1/D3/D5 never fall back to a local Unix socket.
    try:
        apply_product_postgres_env()
        config._nexent_postgres_prereq_error = ""  # type: ignore[attr-defined]
    except (AssetDependencyError, AutomationInfrastructureError) as exc:
        # Preserve collection for non-DB tests.  A DB consumer will surface a
        # connection-level failure that is classified as D0-POSTGRES below.
        config._nexent_postgres_prereq_error = str(exc)  # type: ignore[attr-defined]

    from shared.config import repo_root

    repo = repo_root()
    for source_root in (repo, repo / "backend", repo / "sdk"):
        value = str(source_root)
        if value not in sys.path:
            sys.path.insert(0, value)


def _marker_value(item: pytest.Item, name: str) -> str:
    marker = item.get_closest_marker(name)
    if marker is None or len(marker.args) != 1 or not str(marker.args[0]).strip():
        raise pytest.UsageError(f"{item.nodeid}: requires @{name}(value)")
    return str(marker.args[0]).strip()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    outcome = yield
    report = outcome.get_result()
    redact_report(report, item.funcargs)
    # A setup error/skip never reaches the call phase. Record it immediately;
    # otherwise record the final call result. Teardown failures are surfaced by
    # pytest/JUnit and intentionally do not create a second result for one case.
    if report.when == "setup" and report.passed:
        return
    if report.when not in {"setup", "call"}:
        return
    case_id = _marker_value(item, "case_id")
    stage = _marker_value(item, "stage")
    result_dir: Path | None = item.config._nexent_result_dir  # type: ignore[attr-defined]
    if result_dir is None:
        return
    recorded: set[str] = item.config._nexent_recorded  # type: ignore[attr-defined]
    if case_id in recorded:
        return
    extra: dict[str, str] = {}
    if report.skipped:
        skip_reason = str(report.longrepr)
        if "SKIPPED_BY_POLICY:" in skip_reason:
            result = "SKIPPED_BY_POLICY"
        elif "SKIPPED_BY_SAFETY:" in skip_reason:
            result = "SKIPPED_BY_SAFETY"
        elif "BLOCKED_BY_DEPENDENCY:" in skip_reason:
            result = "BLOCKED_BY_DEPENDENCY"
        else:
            result = "BLOCKED"
        reason = "TEST_SKIPPED: " + skip_reason
    elif report.failed:
        value = call.excinfo.value if call.excinfo is not None else None
        if isinstance(value, AssetDependencyError):
            result = "BLOCKED_BY_DEPENDENCY"
            extra = {
                "dependency_case_id": value.dependency_case_id,
                "asset_role": f"{value.section}.{value.key}",
            }
        elif _database_dependency_failure(value):
            result = "BLOCKED_BY_DEPENDENCY"
            extra = {
                "dependency_case_id": "D0-POSTGRES",
                "asset_role": "services.postgres",
            }
        elif isinstance(value, (AssetTimeoutError, TimeoutError)):
            result = "TIMEOUT"
        elif isinstance(value, AutomationInfrastructureError):
            result = "AUTOMATION_ERROR"
        # pytest.raises(...), pytest.fail(...) and similar assertion helpers
        # raise _pytest.outcomes.Failed rather than AssertionError. They still
        # describe a product-contract failure, not broken test infrastructure.
        elif value is not None and not isinstance(value, (AssertionError, Failed)):
            result = "AUTOMATION_ERROR"
        else:
            result = "FAIL"
        reason = str(report.longrepr)
    else:
        result = "PASS"
        reason = ""
    reason = _redact_reason(reason)[:4000]
    evidence: list[str] = []
    environment_evidence = result_dir / stage.lower() / case_id / 'environment.json'
    if environment_evidence.is_file():
        evidence.append(environment_evidence.relative_to(result_dir).as_posix())
        try:
            environment_record = json.loads(environment_evidence.read_text(encoding='utf-8'))
            extra['environment_recovery'] = str(environment_record.get('recovery', 'UNKNOWN'))
        except (OSError, ValueError):
            extra['environment_recovery'] = 'UNKNOWN'
    if result in {"FAIL", "TIMEOUT", "AUTOMATION_ERROR", "BLOCKED", "BLOCKED_BY_DEPENDENCY"}:
        evidence_path = result_dir / stage.lower() / case_id / "failure.json"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(
            json.dumps({"case_id": case_id, "result": result, "reason": reason}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        evidence.append(evidence_path.relative_to(result_dir).as_posix())
    record = {
        "case_id": case_id,
        "result": result,
        "stage": stage,
        "duration_seconds": round(float(report.duration), 3),
        "failure_reason": reason,
        "analysis": "repository case-local fixed automation",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "evidence": evidence,
        **extra,
    }
    target = result_dir / "checkpoints" / "results.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    recorded.add(case_id)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    seen: dict[str, str] = {}
    planned: dict[str, str] = config._nexent_planned  # type: ignore[attr-defined]
    selected: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    stages: set[str] = set()
    blocked_dependencies = _dependency_blocks()
    feature_flags = load_yaml("environment.yaml").get("features", {})
    disabled_feature_cases = {
        case_id: feature
        for feature, case_ids in FEATURE_TEST_POLICY["required_features"].items()
        if feature_flags.get(feature) is not True
        for case_id in case_ids
    }
    for item in list(items):
        case_id = _marker_value(item, "case_id")
        stage = _marker_value(item, "stage").upper()
        stages.add(stage)
        if case_id in seen:
            raise pytest.UsageError(f"duplicate case_id {case_id}: {seen[case_id]} and {item.nodeid}")
        seen[case_id] = item.nodeid
        if planned and case_id not in planned:
            deselected.append(item)
            continue
        if planned and planned[case_id] != stage:
            raise pytest.UsageError(
                f"{case_id}: implementation stage {stage} does not match execution plan stage {planned[case_id]}"
            )
        selected.append(item)
        if case_id in DATABASE_TEST_CASES:
            item.add_marker(pytest.mark.skip(reason="SKIPPED_BY_POLICY: database and migration tests are excluded"))
        elif case_id in disabled_feature_cases:
            item.add_marker(pytest.mark.skip(reason=(
                "SKIPPED_BY_POLICY: feature " + disabled_feature_cases[case_id]
                + " is disabled in config/environment.yaml"
            )))
        elif case_id in blocked_dependencies:
            item.add_marker(pytest.mark.skip(reason=f"BLOCKED_BY_DEPENDENCY: {blocked_dependencies[case_id]}"))
        recorded: set[str] = item.config._nexent_recorded  # type: ignore[attr-defined]
        if case_id in recorded:
            item.add_marker(pytest.mark.skip(reason="case result already recorded by an earlier asset-producer phase"))
    if deselected:
        items[:] = selected
        config.hook.pytest_deselected(items=deselected)
    result_dir: Path | None = config._nexent_result_dir  # type: ignore[attr-defined]
    if result_dir is not None and stages:
        audit_stage = next(iter(stages)) if len(stages) == 1 else "mixed"
        audit_path = result_dir / audit_stage.lower() / "collection-filter.json"
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(
            json.dumps(
                {
                    "planned_filter_enabled": bool(planned),
                    "collected": len(seen),
                    "selected": len(selected),
                    "deselected_unplanned": sorted(_marker_value(item, "case_id") for item in deselected),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

"""Best-effort cleanup for assets created by the current test batch."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shared.asset_registry import all_registered_assets, mark_asset_state, runtime_dir
from shared.auth import sign_in
from shared.config import load_yaml
from shared.http import client


def _evaluation_agent_id(assets: dict[str, Any], cleanup: dict[str, Any]) -> int | None:
    """Find the exact agent used by this isolated evaluation case."""
    candidates = [cleanup.get("agent_id")]
    agents = assets.get("agents") or {}
    for key in ("basic_id", "evaluation_input_agent_id"):
        candidates.append((agents.get(key) or {}).get("value"))
    inputs = ((assets.get("evaluation") or {}).get("inputs") or {}).get("value") or {}
    if isinstance(inputs, dict):
        candidates.append(inputs.get("agent_id"))
    for value in candidates:
        try:
            if int(value) > 0:
                return int(value)
        except (TypeError, ValueError):
            pass
    return None


async def _delete_partial_evaluation_runs(api: Any, *, assets: dict[str, Any],
                                          cleanup: dict[str, Any], identity: Any,
                                          set_id: int) -> list[int]:
    """Recover runs committed before a failed create response, by exact owner."""
    agent_id = _evaluation_agent_id(assets, cleanup)
    if agent_id is None:
        return []
    listed = await api.get("/agent-evaluations", params={"agent_id": agent_id, "limit": 0})
    if listed.status_code != 200:
        return []
    rows = listed.json().get("data")
    if not isinstance(rows, list):
        return []
    deleted: list[int] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            same_set = int(row.get("evaluation_set_id")) == set_id
            same_agent = int(row.get("agent_id")) == agent_id
            run_id = int(row.get("agent_evaluation_id"))
        except (TypeError, ValueError):
            continue
        if not (same_set and same_agent and run_id > 0):
            continue
        # A genuinely RUNNING evaluation may still be doing useful work.
        # The failed-dispatch residue is PENDING; leave any other status for
        # normal bounded retry or a later explicit cleanup pass.
        if str(row.get("status", "")).upper() != "PENDING":
            continue
        if str(row.get("created_by")) != identity.user_id:
            continue
        if row.get("tenant_id") and str(row["tenant_id"]) != identity.tenant_id:
            continue
        removed = await api.delete(f"/agent-evaluations/{run_id}")
        if removed.status_code not in (200, 404):
            raise RuntimeError(f"owned partial evaluation run deletion returned HTTP {removed.status_code}")
        deleted.append(run_id)
    return deleted


async def cleanup_registered_assets(*, owner_case_ids: set[str] | None = None) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    identities: dict[str, Any] = {}
    entries: list[tuple[str, str, dict[str, Any]]] = []
    assets = all_registered_assets()
    for section, values in assets.items():
        if not isinstance(values, dict):
            continue
        for key, entry in values.items():
            if (
                isinstance(entry, dict)
                and entry.get("source") == "dynamic"
                and entry.get("cleanup")
                and entry.get("state") != "DELETED"
                and (owner_case_ids is None or entry.get("owner_case_id") in owner_case_ids)
            ):
                entries.append((section, key, entry))

    # Normally assets are deleted in reverse registration order. Evaluation
    # sets are the exception: a set/run can retain a reference to its
    # evaluator, so the set must be removed before the evaluator.  Keep this
    # dependency rule deterministic instead of relying on YAML insertion
    # order, which previously made every later preflight fail with HTTP 400.
    def cleanup_order(item: tuple[str, str, dict[str, Any]]) -> tuple[int, int]:
        _section, _key, value = item
        path = str(value.get("cleanup", {}).get("path") or "")
        if _section == 'isolated_tenants':
            priority = 10  # Never cascade before individual user cleanup.
        elif _section == 'isolated_users':
            priority = 9
        elif path.startswith("/agent-evaluations/"):
            priority = 0
        elif path.startswith("/evaluation-sets/"):
            priority = 1
        elif path.startswith("/evaluators/"):
            priority = 3
        elif '/documents?' in path and path.startswith('/indices/'):
            priority = -1
        elif _section == 'tag_values':
            priority = 4
        elif _section == 'tag_definitions':
            priority = 5
        else:
            priority = 2
        return priority, -entries.index(item)

    for section, key, entry in sorted(entries, key=cleanup_order):
        cleanup = entry["cleanup"]
        identity_name = str(cleanup.get("identity") or "tenant_a_user")
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "section": section,
            "key": key,
            "owner_case_id": entry.get("owner_case_id"),
        }
        try:
            if cleanup.get('kind') == 'restore_project_config_file':
                from shared.factories.project_config import restore_project_config_file
                restore_project_config_file(cleanup)
                record['result'] = 'DELETED'
                results.append(record)
                continue
            if cleanup.get('kind') == 'delete_recovery_object':
                from shared.postgres import apply_product_postgres_env
                apply_product_postgres_env()
                from shared.factories.object_storage import delete_owned_object, configured_product_storage
                with configured_product_storage() as storage:
                    delete_owned_object(storage, cleanup['bucket'], cleanup['object_name'])
                mark_asset_state(section, key, 'DELETED')
                record['result'] = 'DELETED'
                results.append(record)
                continue
            if cleanup.get('kind') == 'drop_owned_postgres':
                from shared.factories.scratch_database import drop_scratch
                drop_scratch(cleanup['database'])
                record['result'] = 'DELETED'
                results.append(record)
                continue
            if cleanup.get('kind') == 'delete_owned_aidp_permission':
                import sys
                from shared.config import repo_root
                backend = (repo_root() / 'backend').resolve()
                if not backend.is_dir():
                    raise RuntimeError('Nexent backend source is unavailable for AIDP cleanup')
                if str(backend) not in sys.path:
                    sys.path.insert(0, str(backend))
                from shared.postgres import apply_product_postgres_env
                apply_product_postgres_env()
                from shared.factories.aidp_permission import delete_owned_permission
                delete_owned_permission(
                    kb_id=cleanup['kb_id'], row_id=cleanup['row_id'],
                    tenant_id=cleanup['tenant_id'],
                    owner_user_id=cleanup['owner_user_id'],
                )
                mark_asset_state(section, key, 'DELETED')
                record['result'] = 'DELETED'
                results.append(record)
                continue
            if cleanup.get('kind') in {'delete_owned_knowledge_record', 'delete_owned_lifecycle_file'}:
                import sys
                from shared.config import repo_root
                backend = (repo_root() / 'backend').resolve()
                if not backend.is_dir():
                    raise RuntimeError('Nexent backend source is unavailable for lifecycle cleanup')
                if str(backend) not in sys.path:
                    sys.path.insert(0, str(backend))
                from shared.postgres import apply_product_postgres_env
                apply_product_postgres_env()
                from shared.factories.owned_lifecycle import delete_knowledge, delete_file
                if cleanup['kind'] == 'delete_owned_knowledge_record':
                    delete_knowledge(**{name: cleanup[name] for name in
                        ('index_name', 'knowledge_id', 'tenant_id', 'user_id')})
                else:
                    delete_file(**{name: cleanup[name] for name in
                        ('file_id', 'index_name', 'knowledge_id', 'tenant_id')})
                mark_asset_state(section, key, 'DELETED')
                record['result'] = 'DELETED'
                results.append(record)
                continue
            if cleanup.get('kind') == 'delete_owned_redis_fence':
                import redis
                from shared.factories.redis_target import deployed_redis_urls
                from uuid import UUID
                file_id = str(cleanup['file_id'])
                UUID(hex=file_id)
                general, _backend = deployed_redis_urls()
                wire = redis.from_url(general, socket_timeout=5, socket_connect_timeout=5)
                key_name = 'kb:delete:fence:file:' + file_id
                raw = wire.get(key_name)
                if raw:
                    payload = json.loads(raw)
                    if payload.get('file_id') != file_id:
                        raise RuntimeError('Redis fence ownership mismatch; refusing cleanup')
                    wire.delete(key_name)
                mark_asset_state(section, key, 'DELETED')
                record['result'] = 'DELETED'
                results.append(record)
                continue
            if cleanup.get('kind') == 'stop_owned_container':
                from shared.factories.owned_container import stop_owned_container
                stop_owned_container(cleanup['name'], cleanup['container_id'],
                                     cleanup.get('docker_bin', 'docker'))
                mark_asset_state(section, key, 'DELETED')
                record['result'] = 'DELETED'
                results.append(record)
                continue
            if cleanup.get('kind') == 'restore_platform_capacity':
                from shared.factories.platform_capacity import restore_capacity_probe
                identity = identities.get(identity_name)
                if identity is None:
                    identity = await sign_in(identity_name)
                    identities[identity_name] = identity
                await restore_capacity_probe(
                    identity, key, cleanup['original'], cleanup['expected'],
                )
                record['result'] = 'DELETED'
                results.append(record)
                continue
            identity = identities.get(identity_name)
            if identity is None:
                identity = await sign_in(identity_name)
                identities[identity_name] = identity
            if cleanup.get('kind') in {'delete_isolated_user', 'delete_isolated_tenant'}:
                from shared.factories.tenant import delete_isolated_user, delete_isolated_tenant
                async with client('config', token=identity.access_token) as api:
                    if cleanup['kind'] == 'delete_isolated_user':
                        await delete_isolated_user(api, cleanup['tenant_id'], cleanup['user_id'])
                    else:
                        await delete_isolated_tenant(api, cleanup['tenant_id'])
            elif cleanup.get('kind') == 'revoke_owned_share':
                from shared.factories.sharing import revoke_owned_share
                revoke_owned_share(cleanup['share_token'], identity)
            elif cleanup.get('kind') == 'delete_owned_memory':
                from shared.factories.memory import delete_owned_memory
                await delete_owned_memory(identity, int(cleanup['memory_id']))
            else:
                if cleanup.get('kind'):
                    raise RuntimeError('unsupported cleanup kind')
                service = str(cleanup["service"])
                method = str(cleanup.get("method") or "DELETE").upper()
                path = str(cleanup["path"])
                async with client(service, token=identity.access_token) as api:
                    response = await api.request(method, path, json=cleanup.get("json"))
                    if section == 'owned_knowledge' and method == 'DELETE' and response.status_code == 409:
                        # The product refuses KB deletion while its files are
                        # processing. Retry only this exact owned index, with
                        # a bounded wait; never generalize 409 to success.
                        for _ in range(12):
                            await asyncio.sleep(5)
                            response = await api.request(method, path, json=cleanup.get("json"))
                            if response.status_code != 409:
                                break
                    if (section == 'owned_evaluation_sets' and method == 'DELETE'
                            and path == f'/evaluation-sets/{key}'
                            and response.status_code == 409):
                        # A failed POST /agent-evaluations can still commit a
                        # PENDING run before background dispatch raises. The
                        # response has no run ID, so discover only runs tied
                        # to this exact batch-owned set and test identity.
                        recovered = await _delete_partial_evaluation_runs(
                            api, assets=assets, cleanup=cleanup,
                            identity=identity, set_id=int(key),
                        )
                        if recovered:
                            record['recovered_run_ids'] = recovered
                            response = await api.request(method, path, json=cleanup.get('json'))
                    if (section == 'tag_definitions' and method == 'DELETE'
                            and response.status_code == 409
                            and re.fullmatch(rf'/tag-libraries/([0-9]+)/definitions/{re.escape(str(key))}', path)):
                        # A definition created by this case can retain its
                        # own values even after document assignments vanish.
                        # List within this exact bucket and delete only values
                        # returned for the exact owned definition ID.
                        bucket_path = path.rsplit('/', 1)[0]
                        listed = await api.get(bucket_path)
                        if listed.status_code != 200:
                            record['child_list_http_status'] = listed.status_code
                        else:
                            owned = next((item for item in listed.json()
                                          if str(item.get('definition_id')) == str(key)), None)
                            if owned is not None:
                                for value in owned.get('values') or []:
                                    value_id = value.get('value_id')
                                    if value_id is None:
                                        raise RuntimeError('owned tag value lacks ID')
                                    removed = await api.delete(f'{path}/values/{value_id}')
                                    if removed.status_code not in (200, 404):
                                        record['child_delete_http_status'] = removed.status_code
                                        raise RuntimeError('owned tag value deletion failed')
                                response = await api.request(method, path, json=cleanup.get('json'))
                    if (section == 'owned_knowledge' and method == 'DELETE'
                            and path == f'/indices/{key}' and response.status_code == 409):
                        # This exact batch-owned KB still has unfinished uploads.
                        # Ask the product to cancel/delete only files it reports
                        # under this KB, then retry deleting the parent. Never
                        # delete a foreign index or infer file IDs from a name.
                        listed = await api.get(f'{path}/files')
                        if listed.status_code != 200:
                            record['child_list_http_status'] = listed.status_code
                        else:
                            files = listed.json().get('files') or []
                            if not isinstance(files, list):
                                raise RuntimeError('owned KB file listing is not a list')
                            removed_count = 0
                            for file in files:
                                if not isinstance(file, dict):
                                    raise RuntimeError('owned KB file listing has an invalid row')
                                file_id = file.get('file_id')
                                object_path = file.get('path_or_url')
                                if not file_id or not object_path:
                                    raise RuntimeError('owned KB file lacks an exact ID or object path')
                                removed = await api.request('DELETE', f'{path}/documents', params={
                                    'file_id': str(file_id), 'path_or_url': str(object_path), 'scope': 'full',
                                })
                                if removed.status_code not in (200, 202, 404):
                                    record['child_delete_http_status'] = removed.status_code
                                    raise RuntimeError('owned KB child deletion failed')
                                removed_count += 1
                            record['owned_child_files_deleted'] = removed_count
                            for _ in range(12):
                                response = await api.request(method, path, json=cleanup.get("json"))
                                if response.status_code != 409:
                                    break
                                await asyncio.sleep(5)
                allowed = {int(value) for value in cleanup.get("allowed_statuses", [200, 204, 404])}
                if response.status_code not in allowed:
                    record['http_status'] = response.status_code
                    # A test may already have deleted its owned conversation.
                    # Current runtime maps repeated DELETE to 500. Never accept
                    # that status blindly: verify the owner's history is absent.
                    absent = False
                    if service == 'runtime' and method == 'DELETE' and re.fullmatch(r'/conversation/[0-9]+', path):
                        async with client(service, token=identity.access_token) as api:
                            verified = await api.get(path)
                        if verified.status_code == 200:
                            payload = verified.json()
                            absent = isinstance(payload, dict) and payload.get('code') == 0 and payload.get('data') == []
                    if not absent:
                        raise RuntimeError(f"cleanup returned HTTP {response.status_code}")
                    record['absence_verified'] = True
            record["result"] = "DELETED"
            mark_asset_state(section, key, "DELETED")
        except Exception as exc:  # cleanup must not hide the primary test result
            record["result"] = "ORPHANED"
            # HTTP exception strings may include credentials or request bodies.
            record["reason"] = f'cleanup failed: {type(exc).__name__}'
            mark_asset_state(section, key, "ORPHANED", detail=record['reason'])
        results.append(record)
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--stale-root", type=Path)
    parser.add_argument("--max-age-hours", type=float, default=24.0)
    parser.add_argument(
        "--force",
        action="store_true",
        help="clean registered assets even when the batch contains test failures (validation/manual cleanup only)",
    )
    args = parser.parse_args()
    if args.stale_root:
        aggregate: list[dict[str, Any]] = []
        cutoff = time.time() - max(args.max_age_hours, 0) * 3600
        for registry in args.stale_root.rglob("runtime/resolved-assets.yaml"):
            if registry.stat().st_mtime > cutoff:
                continue
            old_result_dir = registry.parent.parent.resolve()
            os.environ["RESULT_DIR"] = str(old_result_dir)
            cleaned = asyncio.run(cleanup_registered_assets())
            target = registry.parent / "cleanup-results.jsonl"
            target.write_text(
                "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in cleaned),
                encoding="utf-8",
            )
            aggregate.extend({"result_dir": str(old_result_dir), **item} for item in cleaned)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in aggregate),
                encoding="utf-8",
            )
        return 1 if any(item.get("result") == "ORPHANED" for item in aggregate) else 0
    output = args.output
    if output is None:
        root = runtime_dir(required=True)
        assert root is not None
        output = root / "cleanup-results.jsonl"
    retain = False
    try:
        retain_on_failure = bool(load_yaml("asset-policy.yaml").get("cleanup", {}).get("retain_on_failure", True))
    except (FileNotFoundError, ValueError):
        retain_on_failure = True
    result_file = output.parent.parent / "checkpoints" / "results.jsonl"
    if not args.force and retain_on_failure and result_file.is_file():
        failing = {"FAIL", "TIMEOUT", "AUTOMATION_ERROR"}
        for raw in result_file.read_text(encoding="utf-8").splitlines():
            try:
                if json.loads(raw).get("result") in failing:
                    retain = True
                    break
            except (json.JSONDecodeError, AttributeError):
                continue
    if retain:
        results = [{
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "result": "RETAINED",
            "reason": "asset-policy cleanup.retain_on_failure=true and the batch has failures",
        }]
    else:
        results = asyncio.run(cleanup_registered_assets())
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in results), encoding="utf-8")
    return 1 if any(item["result"] == "ORPHANED" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())

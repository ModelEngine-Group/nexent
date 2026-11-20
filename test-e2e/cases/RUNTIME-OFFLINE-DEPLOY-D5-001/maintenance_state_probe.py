# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Seed and observe abandoned Runtime data in the case-owned product database and volume."""

from datetime import datetime, timedelta, timezone
from functools import partial
import hashlib
import json
from pathlib import Path
import re
import sys
from uuid import UUID, uuid5

from sqlalchemy import select

from contracts.constants.environment import AGENT_WORKSPACE_ROOT, MINIO_DEFAULT_BUCKET, MINIO_ENDPOINT
from infrastructure.object_storage.client import minio_client
from infrastructure.rdb.client import get_db_session
from infrastructure.redis.run_state import runtime_state_service as streams
from management.db.automation.models import AgentAutomationRun, AgentAutomationTask
from management.db.conversation.models import ConversationMessage, ConversationRecord
from management.db.evaluation.models import AgentEvaluation, AgentEvaluationCase
from management.db.execution.models import ExecutionReservation
from management.maintenance import _in_cluster_api_reader, require_paused_kubernetes_runtime, run_runtime_maintenance


def workspace_paths(token):
    root = Path(AGENT_WORKSPACE_ROOT)
    mount = Path("/mnt/nexent").resolve(strict=True)
    if not root.is_absolute() or root.parent.resolve(strict=True) != mount or root.name.startswith("."):
        raise RuntimeError("Expected the product workspace directly under the provisioned test mount")
    return root, root.with_name(f".{root.name}-{token}.saved")


def owned_fields(token):
    return {"created_by": token, "updated_by": token, "delete_flag": "N"}


def seed_later_turn(session, token, epoch, now):
    audit = owned_fields(token)
    conversation = ConversationRecord(conversation_title=f"{token}-later", **audit)
    session.add(conversation)
    session.flush()
    conversation_id = conversation.conversation_id
    earlier, completed = [
        ConversationMessage(conversation_id=conversation_id, message_index=index, message_role="assistant",
                            message_content=f"{status}-{token}", status=status, **audit)
        for index, status in enumerate(("streaming", "completed"), 1)
    ]
    execution = ExecutionReservation(
        tenant_id=token, user_id=token, execution_kind="agent", service_role="runtime",
        execution_key=f"conversation:{conversation_id}", owner_instance_id=token, maintenance_epoch=epoch,
        status="COMPLETED", finished_at=now, **audit,
    )
    session.add_all([earlier, completed, execution])
    session.flush()
    return conversation_id, completed.message_id, execution.execution_id


def seed_later_stream(token, conversation_id, message_id, execution_id):
    generation = f"execution:{execution_id}"
    streams.reset_stream(token, conversation_id, generation, required=True, execution_id=execution_id)
    assert streams.bind_execution_message(token, conversation_id, execution_id, message_id)
    replay = {"slot": 0, "payload": {"type": "final_answer", "content": f"completed-{token}"},
              "append": False, "sequence": 1}
    assert streams.append_stream_event(token, conversation_id, f"data: completed-{token}\n\n",
                                       generation=generation, replay_update=replay)
    streams.mark_run_finished(token, conversation_id, "completed", generation=generation)
    streams.mark_stream_completed(token, conversation_id, "completed", generation=generation, event_count=1)
    for key in (streams._run_key, streams._stream_done_key, streams._stream_key, streams._replay_key):
        assert streams.client.expire(key(token, conversation_id), 7200)


def seed(token, epoch):
    root, saved = workspace_paths(token)
    if root.is_symlink() or saved.exists() or (root / token).exists():
        raise RuntimeError("Workspace fixture already exists or is not owned")
    now = datetime.now(timezone.utc)
    audit = owned_fields(token)
    with get_db_session() as session:
        conversation = ConversationRecord(conversation_title=token, **audit)
        session.add(conversation)
        session.flush()
        conversation_id = conversation.conversation_id
        for index, status in enumerate(("streaming", "completed"), 1):
            session.add(ConversationMessage(conversation_id=conversation_id, message_index=index,
                                            message_role="assistant", message_content=f"{status}-{token}",
                                            status=status, **audit))
        for status in ("RUNNING", "COMPLETED"):
            evaluation = AgentEvaluation(tenant_id=token, agent_id=1, agent_version_no=1, evaluation_set_id=1,
                                         status=status, update_time=now - timedelta(hours=1), **audit)
            session.add(evaluation)
            session.flush()
            session.add(AgentEvaluationCase(tenant_id=token, agent_evaluation_id=evaluation.agent_evaluation_id,
                                            evaluation_set_case_id=1, inputs={"query": token}, label={"answer": token},
                                            status=status, **audit))
        task = AgentAutomationTask(tenant_id=token, user_id=token, conversation_id=conversation_id, agent_id=1,
                                   title=token, instruction=token, status="PAUSED", source="AUTOMATION",
                                   schedule_mode="RECURRING", schedule_rule_type="INTERVAL",
                                   schedule_config={"interval_seconds": 3600}, timezone="UTC", timeout_seconds=600,
                                   overlap_policy="SKIP", misfire_policy="FIRE", next_fire_at=now + timedelta(days=1),
                                   lock_owner=token, lock_until=now + timedelta(days=1), **audit)
        session.add(task)
        session.flush()
        for index, status in enumerate(("RUNNING", "SUCCEEDED"), 1):
            session.add(AgentAutomationRun(task_id=task.task_id, tenant_id=token, user_id=token,
                                           conversation_id=conversation_id, scheduled_fire_at=now - timedelta(hours=index),
                                           trigger_type="SCHEDULED", status=status, **audit))
        session.add(ExecutionReservation(tenant_id=token, user_id=token, execution_kind="agent",
                                         service_role="runtime", execution_key=f"conversation:{conversation_id}",
                                         owner_instance_id=token, maintenance_epoch=epoch, status="RUNNING", **audit))
        later_turn = seed_later_turn(session, token, epoch, now)
    workspace = root / token
    run = workspace / token
    run.mkdir(parents=True)
    (run / "run.txt").write_text(f"run-{token}", encoding="utf-8")
    (workspace / "keep.txt").write_text(f"preserve-{token}", encoding="utf-8")
    streams.client.set(f"runtime-d5:preserve:{token}", token)
    streams.client.hset(streams._run_key(token, conversation_id), mapping={"status": "running"})
    seed_later_stream(token, *later_turn)
    return snapshot(token)


def _rows(session, model, column, token):
    records = session.scalars(select(model).where(column == token).order_by(*model.__table__.primary_key.columns))
    return [{field.name: getattr(record, field.name) for field in model.__table__.columns} for record in records]


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def snapshot(token):
    root, saved = workspace_paths(token)
    workspace = (saved if saved.is_dir() else root) / token
    with get_db_session() as session:
        conversations = {row["conversation_title"]: row["conversation_id"] for row in
                         _rows(session, ConversationRecord, ConversationRecord.created_by, token)}
        conversation_id, later_id = conversations[token], conversations[f"{token}-later"]
        rows = {"messages": _rows(session, ConversationMessage, ConversationMessage.conversation_id,
                                  conversation_id),
                "later_messages": _rows(session, ConversationMessage, ConversationMessage.conversation_id, later_id)}
        for name, model in (("evaluations", AgentEvaluation), ("evaluation_cases", AgentEvaluationCase),
                            ("tasks", AgentAutomationTask), ("automation_runs", AgentAutomationRun),
                            ("reservations", ExecutionReservation)):
            rows[name] = _rows(session, model, model.tenant_id, token)
    return {
        **rows,
        "run_file": _digest(workspace / token / "run.txt"),
        "non_run_file": _digest(workspace / "keep.txt"),
        "redis_status": streams.client.hget(streams._run_key(token, conversation_id), "status"),
        "redis_done": streams.client.hget(streams._stream_done_key(token, conversation_id), "status"),
        "later_stream": {
            "run": streams.client.hgetall(streams._run_key(token, later_id)),
            "done": streams.client.hgetall(streams._stream_done_key(token, later_id)),
            "replay": streams.client.hgetall(streams._replay_key(token, later_id)),
            "events": streams.client.xrange(streams._stream_key(token, later_id)),
        },
        "redis_sentinel": streams.client.get(f"runtime-d5:preserve:{token}"),
    }


def block_cleanup(token):
    root, saved = workspace_paths(token)
    if saved.exists() or root.is_symlink() or not (root / token / "keep.txt").is_file():
        raise RuntimeError("Not the expected owned workspace fixture")
    root.rename(saved)
    try:
        with root.open("x", encoding="utf-8") as stream:
            stream.write(token)
    except BaseException:
        if not root.exists():
            saved.rename(root)
        raise


def restore_cleanup(token):
    root, saved = workspace_paths(token)
    if not saved.is_dir() or root.is_symlink() or not root.is_file() or root.read_text(encoding="utf-8") != token:
        raise RuntimeError("Refusing to replace a workspace root not owned by this fault fixture")
    root.unlink()
    saved.rename(root)


def check_live_rejection(token, epoch):
    check_paused = partial(require_paused_kubernetes_runtime, _in_cluster_api_reader(), "nexent", "nexent")
    try:
        run_runtime_maintenance(epoch, f"d5-guard:{token}", check_paused)
    except RuntimeError as exc:
        if str(exc) == "Runtime Deployment must have zero replicas during maintenance":
            return "live-runtime-rejected"
        raise
    raise AssertionError("Maintenance accepted a live Runtime Deployment")


def repeat_completed_batch(token, epoch):
    check_paused = partial(require_paused_kubernetes_runtime, _in_cluster_api_reader(), "nexent", "nexent")
    return run_runtime_maintenance(epoch, f"d5-replay:{token}", check_paused)


def add_run_sentinel(token):
    root, saved = workspace_paths(token)
    if saved.exists() or not (root / token / "keep.txt").is_file():
        raise RuntimeError("Expected the restored, case-owned workspace")
    run = root / token / token
    run.mkdir()
    (run / "run.txt").write_text(f"replay-sentinel-{token}", encoding="utf-8")
    return snapshot(token)["run_file"]


def owned_tool_storage():
    if (MINIO_ENDPOINT, MINIO_DEFAULT_BUCKET) != ("http://nexent-minio:9000", "nexent"):
        raise RuntimeError("Tool receipts require the isolated release's embedded MinIO bucket")
    minio_client._ensure_initialized()
    return minio_client._storage_client.client


def enable_tool_receipts(token):
    root, saved = workspace_paths(token)
    sentinel = root / token / "keep.txt"
    if saved.exists() or sentinel.is_symlink() or not sentinel.is_file():
        raise RuntimeError("Tool receipt versioning requires a seeded workspace owned by this run")
    if sentinel.read_text(encoding="utf-8") != f"preserve-{token}":
        raise RuntimeError("Tool receipt versioning requires the run-owned workspace sentinel")
    client = owned_tool_storage()
    client.put_bucket_versioning(Bucket=MINIO_DEFAULT_BUCKET, VersioningConfiguration={"Status": "Enabled"})
    return client.get_bucket_versioning(Bucket=MINIO_DEFAULT_BUCKET)["Status"]


def read_tool_receipts(token):
    client = owned_tool_storage()
    if client.get_bucket_versioning(Bucket=MINIO_DEFAULT_BUCKET).get("Status") != "Enabled":
        raise RuntimeError("Tool receipt versioning is not enabled")
    prefix = f"workspace/{uuid5(UUID(hex=token), 'owner:user')}/"
    key_pattern = re.compile(re.escape(prefix) + r"[^/]+/outputs/runtime-maintenance-([a-z][a-z0-9-]{0,31})\.txt")
    receipts = {}
    pages = client.get_paginator("list_object_versions").paginate(Bucket=MINIO_DEFAULT_BUCKET, Prefix=prefix)
    for page in pages:
        if any(key_pattern.fullmatch(row["Key"]) for row in page.get("DeleteMarkers", ())):
            raise AssertionError("A tool receipt was deleted before the end of observation")
        for row in page.get("Versions", ()):
            match = key_pattern.fullmatch(row["Key"])
            if match is None:
                continue
            version = row["VersionId"]
            if not version or version == "null":
                raise AssertionError("Expected a versioned tool receipt")
            body = client.get_object(Bucket=MINIO_DEFAULT_BUCKET, Key=row["Key"], VersionId=version)["Body"]
            try:
                digest = hashlib.sha256(body.read(8193)).hexdigest()
            finally:
                body.close()
            receipts.setdefault(match[1], []).append({"key": row["Key"], "version": version, "sha256": digest})
    return receipts


def main():
    action, token, *args = sys.argv[1:]
    if UUID(hex=token).hex != token or len(token) != 32:
        raise ValueError("Expected a run-owned fixture token")
    actions = {"seed": seed, "snapshot": snapshot, "block-cleanup": block_cleanup, "restore-cleanup": restore_cleanup,
               "check-live-rejection": check_live_rejection, "repeat-completed": repeat_completed_batch,
               "add-run-sentinel": add_run_sentinel, "enable-tool-receipts": enable_tool_receipts,
               "read-tool-receipts": read_tool_receipts}
    response = actions[action](token, *args)
    print("D5_STATE " + json.dumps(response, default=str, sort_keys=True))


if __name__ == "__main__":
    main()

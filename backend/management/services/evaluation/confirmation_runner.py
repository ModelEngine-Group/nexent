# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Trusted worker entry point inside the independent evaluator's private deployment."""

import asyncio
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from backend.http.client import create_httpx_client
from contracts.confirmation import ConfirmationPolicy
from contracts.constants import environment
from contracts.evolution import DevelopmentExperimentRequest
from contracts.evolution_metering import confirmation_budget
from contracts.evolution_sources import task_digest
from infrastructure.agentos_client import AgentOSClient
from management.cli.confirmation_manifest import read_private_suite, verify_private_protocol
from management.db.evaluation import confirmation_runs
from management.db.evaluation.confirmation_locks import locked_protocol
from management.services.evaluation import experiments
from management.services.evaluation.confirmation import verified_recipe
from management.services.evaluation.confirmation_results import arm_measurement, comparison_summary
from management.services.evaluation.replay_cases import remove_trial_inputs, stage_verified_input
from nexent.core.concurrency import run_blocking
from nexent.monitor.private_logging import private_evaluation_logging


async def _io(name, fn, *args):
    return await run_blocking(name, fn, *args, lane="control-io", owner="management")


def private_settings(path):
    bucket = environment.EVOLUTION_CONFIRMATION_BUCKET
    if (
        not bucket
        or bucket != environment.MINIO_DEFAULT_BUCKET
        or environment.ENABLE_TELEMETRY
        or not environment.EVOLUTION_CONFIRMATION_RUNTIME_URL
        or not environment.EVOLUTION_CONFIRMATION_STATE_DIR
    ):
        raise ValueError(
            "Configure the independent Runtime, private attachment bucket and worker state with telemetry disabled"
        )
    state = Path(environment.EVOLUTION_CONFIRMATION_STATE_DIR).resolve()
    if state.is_relative_to(Path(path).resolve().parent):
        raise ValueError("Keep trusted worker state outside the submitted suite directory")
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    return bucket, state / "confirmation.sqlite3"


def checkpoint(path, attempt, value=None, phase=None):
    # The deployment owns this directory; it is never supplied or modified by the suite author.
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS measured (attempt TEXT PRIMARY KEY, result TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS in_progress (attempt TEXT PRIMARY KEY, phase TEXT NOT NULL)")
        if phase is not None:
            db.execute("""
                INSERT INTO in_progress (attempt,phase)
                SELECT ?,? WHERE NOT EXISTS (SELECT 1 FROM measured WHERE attempt=?)
                ON CONFLICT DO UPDATE SET phase=excluded.phase WHERE in_progress.phase='staging'
            """, (attempt, phase, attempt))
        if value is not None:
            db.execute(
                "INSERT INTO measured (attempt,result) VALUES (?,?) ON CONFLICT DO NOTHING",
                (attempt, json.dumps(value, allow_nan=False)),
            )
            db.execute("DELETE FROM in_progress WHERE attempt=?", (attempt,))
        found = db.execute("SELECT result FROM measured WHERE attempt=?", (attempt,)).fetchone()
        pending = db.execute("SELECT phase FROM in_progress WHERE attempt=?", (attempt,)).fetchone()
    if found:
        return json.loads(found[0])
    return {"pending_phase": pending[0]} if pending else None


async def _run_locked(tenant, lock_id, path, bucket, ledger):
    authority, protocol = await _io(
        "read-independent-authority", confirmation_runs.run_authority, tenant, lock_id
    )
    recipe, plan = protocol["recipe"], authority["plan"]
    editor, curator = authority["submitted_by"], authority["locked_by"]
    if await verified_recipe(tenant, editor, protocol["experiment_id"], plan) != recipe:
        raise ValueError("Independent candidate changed")
    if (
        plan["evaluator"]["evaluator_type"] != "code"
        and environment.RUNTIME_SERVICE_URL.rstrip("/") != environment.EVOLUTION_CONFIRMATION_RUNTIME_URL
    ):
        raise ValueError("Route the private judge to the independent Runtime before opening the suite")
    manifest, families, tasks = await _io("open-private-suite", read_private_suite, path)
    verify_private_protocol(manifest, families, protocol)
    for stored in await _io(
        "read-independent-result", confirmation_runs.result_for_experiment, tenant, protocol["experiment_id"]
    ):
        if stored["lock_id"] == lock_id and stored["summary"] is not None:
            return stored["summary"]
    req = DevelopmentExperimentRequest.model_validate(plan["request"])
    allowance = confirmation_budget(tenant)
    if allowance is None and authority.get("model_metering") is not None:
        raise ValueError("Restore the locked independent billing configuration before resuming")
    if allowance is not None:
        await _io("freeze-independent-model-budget", confirmation_runs.freeze_model_metering,
                  tenant, curator, protocol, allowance)
        await _io("retire-interrupted-model-leases", confirmation_runs.close_interrupted_attempts, tenant, lock_id)
    client = AgentOSClient(environment.EVOLUTION_CONFIRMATION_RUNTIME_URL, create_httpx_client)
    step_ids = {part.candidate_id for part in req.components or () if part.candidate_type == "skill_step"}
    pairs = []
    for index, digest in enumerate(sorted(tasks)):
        task, paths = tasks[digest]

        def read_material(file):
            local = paths[file["name"]].resolve(strict=True)
            if not local.is_relative_to(Path(path).resolve().parent):
                raise ValueError("Private attachment path changed")
            with local.open("rb") as stream:
                return stream.read(file["size"] + 1)

        measured = {}
        # Alternate order to avoid always charging the same arm for cold starts.
        for arm in ("base", "result") if index % 2 == 0 else ("result", "base"):
            if await _io("check-independent-grant", locked_protocol, tenant, curator, lock_id) != protocol:
                raise ValueError("Independent authority changed")
            spec = await experiments._snapshot(req, tenant, editor, arm)
            if experiments.snapshot_digest(spec) != recipe["snapshots"][arm]:
                raise ValueError("The runtime resource binding differs from the locked comparison")
            attempt = task_digest([protocol["digest"], digest, arm])[:32]
            observation = await _io("read-private-checkpoint", checkpoint, ledger, attempt)
            if observation and observation.get("pending_phase"):
                await _io("remove-interrupted-private-inputs", remove_trial_inputs, editor, attempt, task["attachments"])
                if observation["pending_phase"] == "dispatched":
                    interrupted = {**arm_measurement("invalid", {}, task=task), "interrupted": True}
                    await _io("recheck-independent-grant", locked_protocol, tenant, curator, lock_id)
                    observation = await _io("save-interrupted-private-checkpoint", checkpoint, ledger, attempt, interrupted)
                else:
                    observation = None
            if observation is None:
                job = {
                    "plan": plan,
                    "case_id": digest,
                    "receipt_id": attempt,
                    "trial_id": int(attempt[:7], 16) + 1,
                    "variant": arm,
                    "tenant_id": tenant,
                    "created_by": editor,
                }

                def stage(turn):
                    return stage_verified_input(tenant, editor, task, attempt, turn, read_material)

                async def before_dispatch(turn_index):
                    if await _io("recheck-independent-grant", locked_protocol, tenant, curator, lock_id) != protocol:
                        raise ValueError("Independent authority changed")
                    if turn_index == 0:
                        await _io("mark-private-dispatch", checkpoint, ledger, attempt, None, "dispatched")

                model_attempt = None
                if allowance is not None:
                    model_attempt = await _io(
                        "authorize-independent-model-attempt", confirmation_runs.authorize_model_attempt,
                        tenant, curator, protocol, editor, req.timeout_seconds,
                    )
                    if model_attempt is None:
                        measured[arm] = arm_measurement("invalid", {}, task=task)
                        continue
                    job["evaluation_attempt"] = model_attempt
                try:
                    await _io("mark-private-staging", checkpoint, ledger, attempt, None, "staging")
                    status, details = await asyncio.wait_for(
                        experiments.run_verified_arm(
                            req,
                            job,
                            {"digest": digest, "task": task},
                            spec.model_copy(update={"confirmation_bucket": bucket}),
                            client,
                            stage,
                            before_dispatch=before_dispatch,
                        ),
                        req.timeout_seconds,
                    )
                except TimeoutError:
                    # The preregistered arm budget expired. An upstream outage, in contrast,
                    # interrupts the job and permits a later operator restart of the same lock.
                    status, details = "invalid", {}
                finally:
                    if model_attempt is not None:
                        await _io("close-independent-model-attempt", confirmation_runs.close_model_attempt,
                                  tenant, lock_id, model_attempt)
                await _io("recheck-independent-grant", locked_protocol, tenant, curator, lock_id)
                observation = await _io(
                    "save-private-checkpoint",
                    checkpoint,
                    ledger,
                    attempt,
                    arm_measurement(
                        status, details, task=task, require_selection=req.evaluates_skill_choices(), step_ids=step_ids, mapping=plan.get("tool_mapping"),
                        script_build=plan.get("script_build"), arm=arm, tool_build=plan.get("tool_build")
                    ),
                )
            measured[arm] = observation
        pairs.append((task["family"], measured["base"], measured["result"]))
    if await verified_recipe(tenant, editor, protocol["experiment_id"], plan) != recipe:
        raise ValueError("The evaluated resources changed during the comparison")
    summary = comparison_summary(
        ConfirmationPolicy.model_validate(protocol["policy"]),
        pairs,
        require_guide=req.candidate_type == "skill_step",
        require_new_skill=req.candidate_type == "skill_new",
        required_step_ids=step_ids, require_script=req.candidate_type == "skill_script", require_mapping=req.candidate_type == "tool_mapping",
        require_tool_build=req.candidate_type == "tool_build",
    )
    return await _io(
        "record-independent-result", confirmation_runs.finalize, tenant, curator, protocol, summary
    )


async def run_confirmation(tenant, lock_id, path):
    bucket, ledger = await _io("verify-private-worker", private_settings, path)
    slot = confirmation_runs.execution_slot(lock_id)
    acquire = asyncio.create_task(_io("claim-independent-run", slot.__enter__))
    try:
        await asyncio.shield(acquire)
    except asyncio.CancelledError:
        await acquire
        await _io("release-independent-run", slot.__exit__, None, None, None)
        raise
    try:
        with private_evaluation_logging(True):
            return await _run_locked(tenant, lock_id, path, bucket, ledger)
    finally:
        await _io("release-independent-run", slot.__exit__, None, None, None)

# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Pre-admit evaluation capacity and compensate an unstarted database claim."""

import asyncio
import logging
import threading
import uuid

from nexent.core.concurrency import ManagedTaskSpec


logger = logging.getLogger(__name__)
_dispatch_tasks = set()


class DeferredEvaluation:
    def __init__(self):
        self.ready = threading.Event()
        self.lock = threading.Lock()
        self.cancelled = False
        self.call = None
        self.skip = None

    def cancel(self):
        with self.lock:
            self.cancelled = True
            self.ready.set()

    def bind(self, call, skip):
        with self.lock:
            if self.cancelled:
                return False
            self.call, self.skip = call, skip
            self.ready.set()
            return True

    def run(self, cancel_event):
        while not self.ready.wait(0.05):
            if cancel_event.is_set():
                self.cancel()
        with self.lock:
            call, skip = self.call, self.skip
            cancelled = self.cancelled or cancel_event.is_set()
        if call is not None:
            return skip() if cancelled else call()


async def dispatch_owned_evaluation(tenant_id, user_id, evaluation_id, judge_model_id, executor,
                                    *, manager, coordinator, claim, restore, admission):
    gate = DeferredEvaluation()
    task = asyncio.create_task(_dispatch(gate, tenant_id, user_id, evaluation_id, judge_model_id, executor,
        manager=manager, coordinator=coordinator, claim=claim, restore=restore, admission=admission),
        name='evaluation-admission-' + str(evaluation_id))
    _dispatch_tasks.add(task)

    def completed(done):
        _dispatch_tasks.discard(done)
        if not done.cancelled() and done.exception() is not None:
            logger.warning('Evaluation admission did not complete run_id=%s', evaluation_id)

    task.add_done_callback(completed)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # The owned admission finishes its in-flight DB operation and exact
        # compensation; client cancellation cannot drop that operation's result.
        gate.cancel()
        raise


async def _dispatch(gate, tenant_id, user_id, evaluation_id, judge_model_id, executor,
                    *, manager, coordinator, claim, restore, admission):
    async def control(name, function, *args):
        pending = manager.submit('control-io', ManagedTaskSpec(task_name=name, owner='runtime'), function, *args)
        return await asyncio.shield(asyncio.wrap_future(pending.future))

    admission()
    run_id = uuid.uuid4().hex
    execution = manager.submit('evaluation', ManagedTaskSpec(task_name='agent-evaluation-dispatch', owner='runtime',
        run_id=run_id, close_hook=gate.cancel, pass_cancel_event=True), gate.run)
    lease, claim_time, bound, uncertain = None, None, False, False
    try:
        await manager.wait_until_started(execution)
        lease = await control('reserve-evaluation-owner', lambda: coordinator.reserve(
            tenant_id, user_id, 'evaluation:' + str(evaluation_id), run_id,
            kind='EVALUATION', cancel=gate.cancel))
        coordinator.hold(lease, 'dispatch')

        def worker_done(_):
            try:
                coordinator.finish(lease)
            except Exception:
                coordinator.signal_lost()
                logger.warning('Evaluation worker completion ownership is unknown run_id=%s', run_id)

        execution.future.add_done_callback(worker_done)
        # The per-evaluation protected reservation excludes all other Runtime
        # claims. Publish its exact parent identity before the DB mutation so a
        # crash between claim and response never strands an unassociated claim.
        await control('associate-evaluation-owner', lambda: coordinator.associate(lease, evaluation_id=evaluation_id))
        await control('activate-evaluation-owner', coordinator.activate, lease)
        admission()
        if gate.cancelled:
            return False
        uncertain = True
        claim_time = await control('claim-owned-evaluation', claim, evaluation_id, tenant_id, user_id)
        uncertain = False
        if claim_time is None:
            return False
        admission()
        def execute_owned():
            return executor(tenant_id, user_id, evaluation_id, judge_model_id)

        bound = gate.bind(execute_owned,
                          lambda: restore(evaluation_id, tenant_id, user_id, claim_time))
        return bound
    except BaseException:
        if uncertain and lease is not None:
            # A DB response lost during process cancellation cannot be declared
            # an unstarted success. Preserve the holder for scoped recovery.
            coordinator.signal_lost()
        raise
    finally:
        if not bound:
            gate.cancel()
            if claim_time is not None:
                try:
                    await control('restore-unstarted-evaluation', restore,
                                   evaluation_id, tenant_id, user_id, claim_time)
                except BaseException:
                    uncertain = True
                    coordinator.signal_lost()
        if lease is not None and not uncertain:
            await control('finish-evaluation-admission', lambda: coordinator.finish(lease, holder='dispatch'))

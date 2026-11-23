# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Shared process-local monitoring collection and managed worker lifecycle."""

import json
import logging
from collections import defaultdict
from collections.abc import Mapping
from contextlib import asynccontextmanager
from queue import Empty, Full, Queue
from uuid import uuid4
from zoneinfo import ZoneInfo

from contracts.constants.environment import OPS_MONITORING_ENABLED, OPS_MONITORING_TIMEZONE
from infrastructure.monitoring.contracts import Fact
from infrastructure.monitoring.facts import FACT_MODELS
from infrastructure.monitoring.store import BatchStore, monitoring_engine
from nexent.core.concurrency import LanePolicy, ManagedThreadSpec, ThreadManager
from nexent.monitor.facts import set_fact_sink


logger = logging.getLogger(__name__)
LANE = "monitoring"


def start_worker(name, run):
    manager = ThreadManager(name, {LANE: LanePolicy(LANE, max_workers=1, max_queue_size=0)})
    manager.start()
    execution = manager.register_service(ManagedThreadSpec(name, __name__, lane=LANE), run)
    manager.start_service(execution.execution_id)
    return manager


class Producer:
    """Bounded process-local queue, with stable batches across database retries."""

    def __init__(self, store: BatchStore, zone: ZoneInfo, fact_models: Mapping[str, type[Fact]]):
        self.store = store
        self.zone = zone
        self.fact_models = fact_models
        self.queue = Queue(maxsize=4096)

    def emit(self, event):
        fact = self.fact_models[event["fact_kind"]].model_validate(event)
        try:
            self.queue.put_nowait(fact)
        except Full:
            logger.warning("Ops monitoring queue full kind=%s", fact.fact_kind)

    def drain(self):
        groups = defaultdict(list)
        for _ in range(100):
            try:
                fact = self.queue.get_nowait()
            except Empty:
                break
            groups[fact.tenant_id, fact.fact_kind].append(fact)
        return [
            (uuid4(), tenant, kind,
             json.dumps([fact.model_dump(mode="json", exclude_none=True) for fact in facts], separators=(",", ":")),
             sorted({fact.statistic_day(self.zone) for fact in facts}))
            for (tenant, kind), facts in groups.items()
        ]

    def run(self, cancelled):
        pending = []
        while not cancelled.wait(0.5):
            pending = pending or self.drain()
            while pending and not cancelled.is_set():
                try:
                    self.store.enqueue(*pending[0])
                except Exception as error:
                    logger.warning("Ops monitoring batch pending error=%s", type(error).__name__)
                    break
                pending.pop(0)
        while pending or not self.queue.empty():
            pending = pending or self.drain()
            try:
                self.store.enqueue(*pending[0])
            except Exception as error:
                logger.warning("Ops monitoring shutdown drain failed error=%s", type(error).__name__)
                return
            pending.pop(0)


@asynccontextmanager
async def producer_lifespan(fact_models: Mapping[str, type[Fact]] | None = None):
    if not OPS_MONITORING_ENABLED:
        yield
        return
    store = BatchStore(monitoring_engine())
    producer = Producer(store, ZoneInfo(OPS_MONITORING_TIMEZONE), FACT_MODELS if fact_models is None else fact_models)
    manager = start_worker("monitoring-ingest", producer.run)
    set_fact_sink(producer.emit)
    try:
        yield
    finally:
        set_fact_sink(None)
        try:
            await manager.shutdown(timeout=8)
        finally:
            store.engine.dispose()

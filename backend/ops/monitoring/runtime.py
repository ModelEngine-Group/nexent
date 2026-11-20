# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Ops monitoring client lifecycle and managed background workers."""

import json
import logging
from collections import defaultdict
from collections.abc import Mapping
from contextlib import asynccontextmanager
from queue import Empty, Full, Queue
from uuid import uuid4
from zoneinfo import ZoneInfo

from elasticsearch import Elasticsearch
from sqlalchemy import URL, create_engine

from contracts.constants.environment import (
    ES_API_KEY,
    ES_HOST,
    OPS_MONITORING_ENABLED,
    OPS_MONITORING_REPLICAS,
    OPS_MONITORING_TIMEZONE,
    OPS_POSTGRES_DB,
    NEXENT_POSTGRES_PASSWORD,
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from nexent.core.concurrency import LanePolicy, ManagedThreadSpec, ThreadManager
from nexent.monitor.facts import set_fact_sink
from ops.monitoring.agent import AGENT_MONITORING
from ops.monitoring.contracts import MonitoringKind
from ops.monitoring.model import MODEL_MONITORING, SKILL_MONITORING
from ops.monitoring.search import install_templates
from ops.monitoring.service import Monitoring
from ops.monitoring.store import ControlStore


logger = logging.getLogger(__name__)
LANE = "monitoring"
MONITORING_KINDS = {
    "model": MODEL_MONITORING,
    "agent": AGENT_MONITORING,
    "skill": SKILL_MONITORING,
}


def control_store():
    if not POSTGRES_HOST or not POSTGRES_USER or not OPS_POSTGRES_DB:
        raise RuntimeError("Ops monitoring requires the Nexent PostgreSQL connection")
    if OPS_POSTGRES_DB == (POSTGRES_DB or "nexent"):
        raise RuntimeError("Ops monitoring requires an independent PostgreSQL database")
    url = URL.create("postgresql+psycopg2", username=POSTGRES_USER, password=NEXENT_POSTGRES_PASSWORD,
                     host=POSTGRES_HOST, port=POSTGRES_PORT, database=OPS_POSTGRES_DB)
    return ControlStore(create_engine(url, pool_size=4, max_overflow=2, pool_pre_ping=True,
                                      connect_args={"connect_timeout": 3, "options": "-c lock_timeout=4000"}))


def _worker(name, run):
    manager = ThreadManager(name, {LANE: LanePolicy(LANE, max_workers=1, max_queue_size=0)})
    manager.start()
    execution = manager.register_service(ManagedThreadSpec(name, __name__, lane=LANE), run)
    manager.start_service(execution.execution_id)
    return manager


class Producer:
    """Bounded process-local queue, with stable batches across database retries."""

    def __init__(self, store: ControlStore, zone: ZoneInfo, kinds: Mapping[str, MonitoringKind]):
        self.store = store
        self.zone = zone
        self.kinds = kinds
        self.queue = Queue(maxsize=4096)

    def emit(self, event):
        fact = self.kinds[event["fact_kind"]].fact_model.model_validate(event)
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
async def producer_lifespan():
    if not OPS_MONITORING_ENABLED:
        yield
        return
    store = control_store()
    producer = Producer(store, ZoneInfo(OPS_MONITORING_TIMEZONE), MONITORING_KINDS)
    manager = _worker("monitoring-ingest", producer.run)
    set_fact_sink(producer.emit)
    try:
        yield
    finally:
        set_fact_sink(None)
        try:
            await manager.shutdown(timeout=8)
        finally:
            store.engine.dispose()


@asynccontextmanager
async def ops_monitoring_lifespan(app):
    if not OPS_MONITORING_ENABLED:
        yield
        return
    if not ES_HOST:
        raise RuntimeError("Ops monitoring requires an Elasticsearch endpoint")
    store = control_store()
    es = Elasticsearch(ES_HOST, api_key=ES_API_KEY or None, request_timeout=10, max_retries=0)
    manager = None
    try:
        store.verify_schema()
        install_templates(es, OPS_MONITORING_REPLICAS, MONITORING_KINDS.values())
        service = Monitoring(store, es, ZoneInfo(OPS_MONITORING_TIMEZONE), MONITORING_KINDS)

        def run(cancelled):
            while not cancelled.is_set():
                try:
                    service.tick()
                except Exception as error:
                    logger.warning("Ops monitoring cycle failed error=%s", type(error).__name__)
                cancelled.wait(1)

        manager = _worker("ops-monitoring", run)
        app.state.monitoring = service
        yield
    finally:
        if manager is not None:
            await manager.shutdown(timeout=12)
        es.close()
        store.engine.dispose()

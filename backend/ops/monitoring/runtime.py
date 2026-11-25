# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Ops-only Elasticsearch consumption and daily publication lifecycle."""

import logging
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo

from elasticsearch import Elasticsearch

from contracts.constants.environment import (
    ES_API_KEY, ES_HOST, OPS_MONITORING_ENABLED, OPS_MONITORING_REPLICAS, OPS_MONITORING_TIMEZONE,
)
from infrastructure.monitoring.runtime import start_worker
from infrastructure.monitoring.store import monitoring_engine
from ops.monitoring.agent import AGENT_MONITORING
from ops.monitoring.model import MODEL_MONITORING, SKILL_MONITORING
from ops.monitoring.search import install_templates
from ops.monitoring.service import Monitoring
from ops.monitoring.store import ControlStore


logger = logging.getLogger(__name__)
MONITORING_KINDS = {
    "model": MODEL_MONITORING,
    "agent": AGENT_MONITORING,
    "skill": SKILL_MONITORING,
}


def control_store():
    return ControlStore(monitoring_engine())


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

        manager = start_worker("ops-monitoring", run)
        app.state.monitoring = service
        yield
    finally:
        if manager is not None:
            await manager.shutdown(timeout=12)
        es.close()
        store.engine.dispose()

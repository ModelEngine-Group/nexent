"""Ingestion event orchestration service for external memory providers.

Coordinates the full ingest pipeline: unit filtering by global whitelist,
idempotency key generation, provider dispatch, and event logging.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

from consts.const import EXTERNAL_MEMORY_DEFAULT_ALLOWED_UNIT_TYPES
from database import memory_external_ingest_event_log_db, memory_provider_config_param_db
from nexent.memory.models import (
    MemoryIngestRequest,
    MemoryIngestResult,
    MemoryIngestUnit,
)
from services.memory_external_provider_service import MemoryExternalProviderService
from services.memory_provider_config_service import MemoryProviderConfigService

logger = logging.getLogger("memory_ingestion_event_service")


class MemoryIngestionEventService:
    """Orchestrate ingest events across external memory providers."""

    def __init__(
        self,
        config_service: MemoryProviderConfigService,
        provider_service: MemoryExternalProviderService,
    ):
        self._config_service = config_service
        self._provider_service = provider_service

    async def send_ingest(
        self,
        provider_config_id: int,
        tenant_id: str,
        user_id: str,
        agent_id: str,
        conversation_id: str,
        event_type: str,
        event_id: str,
        units: List[MemoryIngestUnit],
    ) -> MemoryIngestResult:
        """Send an ingest event to a single provider.

        Filters units by the global whitelist, builds an idempotency key,
        dispatches to the provider, and logs the result.

        Returns:
            Ingest result from the provider, or a disabled/skipped result.
        """
        config = self._config_service.get_provider(provider_config_id)
        if config is None or not config.get("enabled"):
            return MemoryIngestResult(
                provider=config.get("provider_name", "unknown") if config else "unknown",
                status="disabled",
            )

        provider_name = config.get("provider_name", "unknown")

        filtered = self._filter_units(
            units, list(EXTERNAL_MEMORY_DEFAULT_ALLOWED_UNIT_TYPES)
        )
        if not filtered:
            logger.warning(
                "event=external_memory_ingest_filtered_empty tenant_id=%s provider=%s "
                "event_type=%s event_id=%s input_unit_count=%d allowed_unit_types=%s",
                tenant_id,
                provider_name,
                event_type,
                event_id,
                len(units),
                ",".join(sorted(EXTERNAL_MEMORY_DEFAULT_ALLOWED_UNIT_TYPES)),
            )
            return MemoryIngestResult(
                provider=provider_name,
                status="ok",
                accepted_count=0,
            )

        idem_key = self._build_idempotency_key(
            tenant_id, agent_id, user_id, conversation_id, event_type, event_id
        )

        params = memory_provider_config_param_db.get_params(provider_config_id)

        request = self._build_ingest_request(
            tenant_id, user_id, agent_id, conversation_id, idem_key, filtered
        )

        result = await self._provider_service.ingest(config, params, request)

        self._log_event(
            provider_name, tenant_id, user_id, agent_id,
            conversation_id, event_id, idem_key, filtered, result,
        )

        return result

    async def send_ingest_all_enabled(
        self,
        tenant_id: str,
        user_id: str,
        agent_id: str,
        conversation_id: str,
        event_type: str,
        event_id: str,
        units: List[MemoryIngestUnit],
    ) -> List[MemoryIngestResult]:
        """Fan out an ingest event to all enabled providers in parallel.

        Uses ``return_exceptions=True`` so one provider failure does not
        prevent others from receiving the event.
        """
        configs = self._config_service.get_enabled_providers(tenant_id)
        if not configs:
            logger.info(
                "event=external_memory_ingest_fanout_skipped tenant_id=%s "
                "event_type=%s event_id=%s reason=no_enabled_providers",
                tenant_id,
                event_type,
                event_id,
            )
            return []

        logger.info(
            "event=external_memory_ingest_fanout_started tenant_id=%s event_type=%s "
            "event_id=%s provider_count=%d unit_count=%d",
            tenant_id,
            event_type,
            event_id,
            len(configs),
            len(units),
        )

        tasks = [
            self.send_ingest(
                c["provider_config_id"], tenant_id, user_id,
                agent_id, conversation_id, event_type, event_id, units,
            )
            for c in configs
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        final: List[MemoryIngestResult] = []
        for r in results:
            if isinstance(r, MemoryIngestResult):
                final.append(r)
            elif isinstance(r, Exception):
                logger.warning(
                    "Provider ingest raised exception: %s", r, exc_info=True
                )
                final.append(MemoryIngestResult(
                    provider="unknown",
                    status="error",
                    message=str(r),
                ))
        logger.info(
            "event=external_memory_ingest_fanout_completed tenant_id=%s event_type=%s "
            "event_id=%s provider_count=%d result_count=%d error_count=%d",
            tenant_id,
            event_type,
            event_id,
            len(configs),
            len(final),
            sum(result.status == "error" for result in final),
        )
        return final

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _filter_units(
        units: List[MemoryIngestUnit], allowed_types: List[str]
    ) -> List[MemoryIngestUnit]:
        """Filter ingest units to only those with allowed unit_types."""
        allowed = set(allowed_types)
        return [u for u in units if u.unit_type in allowed]

    @staticmethod
    def _build_idempotency_key(
        tenant_id: str,
        agent_id: str,
        user_id: str,
        conversation_id: str,
        event_type: str,
        event_id: str,
    ) -> str:
        """Build a deterministic idempotency key for ingest deduplication.

        Format: ``nexent:{tenant}:{agent}:{user}:{conversation}:{event_type}:{event_id}``
        """
        return (
            f"nexent:{tenant_id}:{agent_id}:{user_id}"
            f":{conversation_id}:{event_type}:{event_id}"
        )

    @staticmethod
    def _build_ingest_request(
        tenant_id: str,
        user_id: str,
        agent_id: str,
        conversation_id: str,
        idempotency_key: str,
        units: List[MemoryIngestUnit],
    ) -> MemoryIngestRequest:
        return MemoryIngestRequest(
            tenant_id=tenant_id,
            user_id=user_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
            units=units,
            idempotency_key=idempotency_key,
        )

    @staticmethod
    def _log_event(
        provider_name: str,
        tenant_id: str,
        user_id: str,
        agent_id: str,
        conversation_id: str,
        event_id: str,
        idempotency_key: str,
        units: List[MemoryIngestUnit],
        result: MemoryIngestResult,
    ) -> None:
        """Persist an ingest event to the log table."""
        unit_ids = ",".join(u.event_id for u in units)
        response_summary = result.message or f"status={result.status}"

        log_data: Dict[str, Any] = {
            "provider": provider_name,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "agent_id": agent_id,
            "conversation_id": conversation_id,
            "event_id": event_id,
            "idempotency_key": idempotency_key,
            "unit_ids": unit_ids,
            "response_status": result.status,
            "response_summary": response_summary,
        }

        log_id = memory_external_ingest_event_log_db.insert_event_log(log_data)
        if log_id is None:
            logger.warning(
                "Failed to insert ingest event log for provider=%s, "
                "idempotency_key=%s",
                provider_name, idempotency_key,
            )

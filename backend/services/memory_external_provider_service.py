"""Bridge service between backend provider configurations and the SDK provider system.

Constructs provider instances from stored EAV parameters, executes search and
ingest operations with error handling per the error matrix (Functional Design §12),
and provides fan-out methods for all enabled providers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import nullcontext
from typing import Any, Dict, List, Optional, Union

from database import memory_provider_config_db
from consts import const as consts
from nexent.memory.models import (
    MemoryIngestRequest,
    MemoryIngestResult,
    MemorySearchRequest,
    MemorySearchResult,
    ProviderErrorCode,
)
from nexent.memory.providers.base import (
    IngestibleMemoryProvider,
    SearchableMemoryProvider,
)
from nexent.memory.providers.retry import (
    DegradableProviderError,
    NonRetryableProviderError,
    RetryableProviderError,
    RetryConfig,
    execute_with_retry,
)
from services.memory_provider_config_service import MemoryProviderConfigService
from services.memory_provider_plugin_loader import PluginLoader

logger = logging.getLogger("memory_external_provider_service")

try:
    from opentelemetry import metrics as _otel_metrics
    from opentelemetry import trace as _otel_trace

    _meter = _otel_metrics.get_meter(__name__)
    _tracer = _otel_trace.get_tracer(__name__)
    _provider_requests_total = _meter.create_counter(
        "nexent.memory.external_provider.requests",
        description="Logical external memory provider requests",
        unit="requests",
    )
    _provider_duration = _meter.create_histogram(
        "nexent.memory.external_provider.duration",
        description="External memory provider request duration",
        unit="s",
    )
    _provider_search_results = _meter.create_histogram(
        "nexent.memory.external_provider.search.results",
        description="External memory search results returned",
        unit="results",
    )
    _provider_ingest_accepted = _meter.create_counter(
        "nexent.memory.external_provider.ingest.accepted",
        description="External memory ingest units accepted",
        unit="units",
    )
    _provider_ingest_rejected = _meter.create_counter(
        "nexent.memory.external_provider.ingest.rejected",
        description="External memory ingest units rejected",
        unit="units",
    )
except Exception:  # pragma: no cover - telemetry is optional
    _tracer = None
    _provider_requests_total = None
    _provider_duration = None
    _provider_search_results = None
    _provider_ingest_accepted = None
    _provider_ingest_rejected = None

_provider_service: Optional["MemoryExternalProviderService"] = None

_NON_RETRYABLE_DISABLE_CODES = {
    ProviderErrorCode.UNAUTHORIZED,
    ProviderErrorCode.FORBIDDEN,
}


class _ProviderTelemetry:
    """Fail-open OTel recorder for one logical provider operation."""

    def __init__(self, operation: str, provider_name: str, provider_config_id: Optional[int]):
        self.operation = operation
        self.provider_name = provider_name
        self.provider_config_id = provider_config_id
        self.started_at = time.perf_counter()
        try:
            self.span_context = (
                nullcontext(None)
                if _tracer is None
                else _tracer.start_as_current_span(
                    "nexent.memory.external_provider",
                    attributes={
                        "memory.operation": operation,
                        "memory.provider.name": provider_name,
                        "memory.provider.config_id": provider_config_id or 0,
                    },
                )
            )
        except Exception:
            logger.debug("External provider span creation failed", exc_info=True)
            self.span_context = nullcontext(None)

    def finish(
        self,
        span: Any,
        *,
        outcome: str,
        error_code: str = "none",
        result_count: Optional[int] = None,
        accepted_count: Optional[int] = None,
        rejected_count: Optional[int] = None,
    ) -> None:
        attributes = {
            "operation": self.operation,
            "provider": self.provider_name,
            "outcome": outcome,
            "error_code": error_code,
        }
        try:
            if _provider_requests_total is not None:
                _provider_requests_total.add(1, attributes)
            if _provider_duration is not None:
                _provider_duration.record(time.perf_counter() - self.started_at, attributes)
            if result_count is not None and _provider_search_results is not None:
                _provider_search_results.record(result_count, attributes)
            if accepted_count and _provider_ingest_accepted is not None:
                _provider_ingest_accepted.add(accepted_count, attributes)
            if rejected_count and _provider_ingest_rejected is not None:
                _provider_ingest_rejected.add(rejected_count, attributes)
            if span is not None:
                span.set_attribute("memory.outcome", outcome)
                span.set_attribute("memory.error.code", error_code)
                if result_count is not None:
                    span.set_attribute("memory.result.count", result_count)
                if accepted_count is not None:
                    span.set_attribute("memory.unit.accepted_count", accepted_count)
                if rejected_count is not None:
                    span.set_attribute("memory.unit.rejected_count", rejected_count)
        except Exception:
            logger.debug("External provider telemetry recording failed", exc_info=True)


def _error_code(exc: Exception) -> str:
    error = getattr(exc, "error", None)
    code = getattr(error, "code", None)
    return str(getattr(code, "value", code) or "unknown")


class MemoryExternalProviderService:
    """Bridge between stored provider configurations and SDK provider instances."""

    def __init__(
        self,
        plugin_loader: PluginLoader,
        config_service: MemoryProviderConfigService,
    ):
        self._plugin_loader = plugin_loader
        self._config_service = config_service

    def build_provider(
        self, config: Dict[str, Any], params: Dict[str, str]
    ) -> Union[SearchableMemoryProvider, IngestibleMemoryProvider]:
        """Construct a provider instance from stored configuration and parameters.

        Extracts ``plugin.name`` and passes the remaining ``plugin.*`` parameters
        to the plugin loader without their storage namespace prefix. Also includes
        ``timeout_seconds`` from provider config.
        """
        plugin_name = params.get("plugin.name")
        if not plugin_name:
            raise ValueError("params must contain 'plugin.name'")

        plugin_config = {
            key.removeprefix("plugin."): value
            for key, value in params.items()
            if key.startswith("plugin.") and key != "plugin.name"
        }
        plugin_info = self._plugin_loader.get_plugin(plugin_name)
        if plugin_info is not None:
            schema_keys = {field["key"] for field in plugin_info.config_schema}
            for key in schema_keys:
                if key not in plugin_config and key in params:
                    plugin_config[key] = params[key]
        # Pass timeout_seconds from provider config to plugin
        if "timeout_seconds" in config:
            plugin_config["timeout_seconds"] = config["timeout_seconds"]
        return self._plugin_loader.build_provider(plugin_name, plugin_config)

    async def search(
        self,
        config: Dict[str, Any],
        params: Dict[str, str],
        request: MemorySearchRequest,
        limit: int = 5,
    ) -> List[MemorySearchResult]:
        """Execute a search against a single provider with error handling.

        Args:
            config: Provider config dict (from config DB).
            params: Unmasked EAV parameters.
            request: The search request to forward.
            limit: Maximum results to return.

        Returns:
            List of search results from the provider.
        """
        provider_name = config.get("provider_name", "unknown")
        provider_config_id = config.get("provider_config_id")
        telemetry = _ProviderTelemetry("search", provider_name, provider_config_id)

        with telemetry.span_context as span:
            try:
                provider = self.build_provider(config, params)

                async def _do_search() -> List[MemorySearchResult]:
                    return await provider.search(request, limit=limit)

                results = await execute_with_retry(
                    _do_search,
                    RetryConfig(),
                    operation_name=f"search({provider_name})",
                )
                telemetry.finish(span, outcome="success", result_count=len(results))
                return results
            except NonRetryableProviderError as exc:
                telemetry.finish(
                    span, outcome="error", error_code=_error_code(exc), result_count=0
                )
                self._handle_non_retryable(provider_config_id, provider_name, exc)
                return []
            except DegradableProviderError as exc:
                telemetry.finish(
                    span, outcome="degraded", error_code=_error_code(exc), result_count=0
                )
                logger.warning(
                    "Degradable error from provider %s: %s",
                    provider_name, exc, exc_info=True,
                )
                return []
            except RetryableProviderError as exc:
                telemetry.finish(
                    span, outcome="error", error_code=_error_code(exc), result_count=0
                )
                logger.warning(
                    "Retryable error from provider %s after all retries: %s",
                    provider_name, exc, exc_info=True,
                )
                return []
            except ValueError:
                telemetry.finish(
                    span, outcome="error", error_code="configuration", result_count=0
                )
                logger.warning(
                    "Invalid configuration for provider %s",
                    provider_name, exc_info=True,
                )
                return []
            except Exception:
                telemetry.finish(span, outcome="error", error_code="unexpected", result_count=0)
                logger.warning(
                    "Unexpected error searching provider %s",
                    provider_name, exc_info=True,
                )
                return []

    async def ingest(
        self,
        config: Dict[str, Any],
        params: Dict[str, str],
        request: MemoryIngestRequest,
    ) -> MemoryIngestResult:
        """Execute an ingest against a single provider with error handling.

        Handles the full error matrix:
        - ``unsupported_unit_type``: remove problematic units, retry once
        - ``partial_acceptance``: return accepted units
        - ``unauthorized``/``forbidden``: disable provider
        - Other errors: log and return error result
        """
        provider_name = config.get("provider_name", "unknown")
        provider_config_id = config.get("provider_config_id")
        telemetry = _ProviderTelemetry("ingest", provider_name, provider_config_id)

        with telemetry.span_context as span:
            try:
                provider = self.build_provider(config, params)

                async def _do_ingest() -> MemoryIngestResult:
                    return await provider.ingest(request)

                result = await execute_with_retry(
                    _do_ingest,
                    RetryConfig(),
                    operation_name=f"ingest({provider_name})",
                )
                telemetry.finish(
                    span,
                    outcome=result.status,
                    accepted_count=getattr(result, "accepted_count", 0),
                    rejected_count=getattr(result, "rejected_count", 0),
                )
                return result
            except DegradableProviderError as exc:
                result = await self._handle_degradable_ingest(
                    provider, provider_name, request, exc
                )
                telemetry.finish(
                    span,
                    outcome=result.status,
                    error_code=_error_code(exc),
                    accepted_count=getattr(result, "accepted_count", 0),
                    rejected_count=getattr(result, "rejected_count", 0),
                )
                return result
            except NonRetryableProviderError as exc:
                telemetry.finish(span, outcome="error", error_code=_error_code(exc))
                self._handle_non_retryable(provider_config_id, provider_name, exc)
                return MemoryIngestResult(
                    provider=provider_name,
                    status="error",
                    message=str(exc),
                )
            except RetryableProviderError as exc:
                telemetry.finish(span, outcome="error", error_code=_error_code(exc))
                logger.warning(
                    "Retryable error from provider %s after all retries: %s",
                    provider_name, exc, exc_info=True,
                )
                return MemoryIngestResult(
                    provider=provider_name,
                    status="error",
                    message=str(exc),
                )
            except ValueError:
                telemetry.finish(span, outcome="error", error_code="configuration")
                logger.warning(
                    "Invalid configuration for provider %s",
                    provider_name, exc_info=True,
                )
                return MemoryIngestResult(
                    provider=provider_name,
                    status="error",
                    message="Invalid provider configuration",
                )
            except Exception:
                telemetry.finish(span, outcome="error", error_code="unexpected")
                logger.warning(
                    "Unexpected error ingesting to provider %s",
                    provider_name, exc_info=True,
                )
                return MemoryIngestResult(
                    provider=provider_name,
                    status="error",
                    message="Unexpected error",
                )

    async def search_all_enabled(
        self,
        tenant_id: str,
        request: MemorySearchRequest,
        limit: int = 5,
    ) -> List[MemorySearchResult]:
        """Search all enabled providers in parallel and concatenate results.

        Individual provider failures are logged but do not affect other
        providers. Results are concatenated without reranking since different
        providers use incomparable score systems.
        """
        providers = self._config_service.get_enabled_providers(tenant_id)
        if not providers:
            return []

        async def _search_one(p: Dict[str, Any]) -> List[MemorySearchResult]:
            try:
                return await self.search(
                    p, p["params"], request, limit=limit
                )
            except Exception:
                logger.warning(
                    "Provider %s search failed",
                    p.get("provider_name", "unknown"),
                    exc_info=True,
                )
                return []

        results = await asyncio.gather(
            *[_search_one(p) for p in providers]
        )

        combined: List[MemorySearchResult] = []
        for result_list in results:
            combined.extend(result_list)
        return combined

    async def ingest_all_enabled(
        self,
        tenant_id: str,
        request: MemoryIngestRequest,
    ) -> List[MemoryIngestResult]:
        """Ingest to all enabled providers in parallel.

        Individual provider failures are caught and returned as error results
        so one provider failure does not affect others.
        """
        providers = self._config_service.get_enabled_providers(tenant_id)
        if not providers:
            return []

        async def _ingest_one(p: Dict[str, Any]) -> MemoryIngestResult:
            try:
                return await self.ingest(p, p["params"], request)
            except Exception:
                logger.warning(
                    "Provider %s ingest failed",
                    p.get("provider_name", "unknown"),
                    exc_info=True,
                )
                return MemoryIngestResult(
                    provider=p.get("provider_name", "unknown"),
                    status="error",
                    message="Unexpected failure",
                )

        results = await asyncio.gather(
            *[_ingest_one(p) for p in providers],
            return_exceptions=True,
        )

        final: List[MemoryIngestResult] = []
        for r in results:
            if isinstance(r, MemoryIngestResult):
                final.append(r)
            elif isinstance(r, Exception):
                logger.warning("Provider ingest raised: %s", r, exc_info=True)
                final.append(MemoryIngestResult(
                    provider="unknown",
                    status="error",
                    message=str(r),
                ))
        return final

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _handle_non_retryable(
        self,
        provider_config_id: Optional[int],
        provider_name: str,
        exc: NonRetryableProviderError,
    ) -> None:
        """Disable provider for auth errors, log warning for others."""
        error_code = exc.error.code if exc.error else None
        if error_code in _NON_RETRYABLE_DISABLE_CODES and provider_config_id:
            logger.warning(
                "Disabling provider %s (id=%d) due to %s error: %s",
                provider_name, provider_config_id, error_code, exc,
            )
            memory_provider_config_db.disable_provider_config(
                provider_config_id
            )
        else:
            logger.warning(
                "Non-retryable error from provider %s: %s",
                provider_name, exc, exc_info=True,
            )

    async def _handle_degradable_ingest(
        self,
        provider: Union[SearchableMemoryProvider, IngestibleMemoryProvider],
        provider_name: str,
        request: MemoryIngestRequest,
        exc: DegradableProviderError,
    ) -> MemoryIngestResult:
        """Handle degradable ingest errors by removing problematic units and retrying once.

        For ``unsupported_unit_type``: remove the flagged units and retry.
        For ``partial_acceptance``: return the accepted units from the result.
        """
        error_code = exc.error.code if exc.error else None

        if error_code == ProviderErrorCode.PARTIAL_ACCEPTANCE:
            logger.info(
                "Provider %s partially accepted units", provider_name
            )
            return MemoryIngestResult(
                provider=provider_name,
                status="degraded",
                message="Partial acceptance",
            )

        removable_unit_ids = set(exc.removable_units) if exc.removable_units else set()
        if not removable_unit_ids:
            logger.warning(
                "Degradable error from %s but no removable units specified",
                provider_name,
            )
            return MemoryIngestResult(
                provider=provider_name,
                status="degraded",
                message=str(exc),
            )

        filtered_units = [
            u for u in request.units
            if u.event_id not in removable_unit_ids
        ]
        if not filtered_units:
            logger.warning(
                "All units removed for provider %s after degradable error",
                provider_name,
            )
            return MemoryIngestResult(
                provider=provider_name,
                status="degraded",
                accepted_count=0,
                message="All units rejected",
            )

        retry_request = request.model_copy(update={"units": filtered_units})

        try:
            result = await provider.ingest(retry_request)
            result.status = "degraded"
            return result
        except Exception:
            logger.warning(
                "Retry after degradable error failed for provider %s",
                provider_name, exc_info=True,
            )
            return MemoryIngestResult(
                provider=provider_name,
                status="error",
                message="Retry after degradation failed",
            )


def get_memory_external_provider_service() -> MemoryExternalProviderService:
    """Return the process-wide external provider service used by Agent runtime."""
    global _provider_service
    if _provider_service is None:
        plugin_loader = PluginLoader(consts.MEMORY_PROVIDER_PLUGINS_DIR)
        plugin_loader.load_all()
        config_service = MemoryProviderConfigService(plugin_loader)
        _provider_service = MemoryExternalProviderService(
            plugin_loader=plugin_loader,
            config_service=config_service,
        )
    return _provider_service

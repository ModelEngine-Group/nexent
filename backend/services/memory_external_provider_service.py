"""Bridge service between backend provider configurations and the SDK provider system.

Constructs provider instances from stored EAV parameters, executes search and
ingest operations with error handling per the error matrix (Functional Design §12),
and provides fan-out methods for all enabled providers.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Union

from database import memory_provider_config_db
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

_NON_RETRYABLE_DISABLE_CODES = {
    ProviderErrorCode.UNAUTHORIZED,
    ProviderErrorCode.FORBIDDEN,
}


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

        Extracts ``plugin.name`` and passes all other parameters (except plugin.name)
        to the plugin loader.
        """
        plugin_name = params.get("plugin.name")
        if not plugin_name:
            raise ValueError("params must contain 'plugin.name'")

        plugin_config = {
            k: v for k, v in params.items() if k != "plugin.name"
        }
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
        provider = self.build_provider(config, params)
        provider_name = config.get("provider_name", "unknown")
        provider_config_id = config.get("provider_config_id")

        async def _do_search() -> List[MemorySearchResult]:
            return await provider.search(request, limit=limit)

        try:
            return await execute_with_retry(
                _do_search,
                RetryConfig(),
                operation_name=f"search({provider_name})",
            )
        except NonRetryableProviderError as exc:
            self._handle_non_retryable(provider_config_id, provider_name, exc)
            return []
        except DegradableProviderError as exc:
            logger.warning(
                "Degradable error from provider %s: %s",
                provider_name, exc, exc_info=True,
            )
            return []
        except RetryableProviderError as exc:
            logger.warning(
                "Retryable error from provider %s after all retries: %s",
                provider_name, exc, exc_info=True,
            )
            return []
        except Exception:
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
        provider = self.build_provider(config, params)
        provider_name = config.get("provider_name", "unknown")
        provider_config_id = config.get("provider_config_id")

        async def _do_ingest() -> MemoryIngestResult:
            return await provider.ingest(request)

        try:
            return await execute_with_retry(
                _do_ingest,
                RetryConfig(),
                operation_name=f"ingest({provider_name})",
            )
        except DegradableProviderError as exc:
            return await self._handle_degradable_ingest(
                provider, provider_name, request, exc
            )
        except NonRetryableProviderError as exc:
            self._handle_non_retryable(provider_config_id, provider_name, exc)
            return MemoryIngestResult(
                provider=provider_name,
                status="error",
                message=str(exc),
            )
        except RetryableProviderError as exc:
            logger.warning(
                "Retryable error from provider %s after all retries: %s",
                provider_name, exc, exc_info=True,
            )
            return MemoryIngestResult(
                provider=provider_name,
                status="error",
                message=str(exc),
            )
        except Exception:
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

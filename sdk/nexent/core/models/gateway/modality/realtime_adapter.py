"""Realtime adapter (OpenAI Realtime API) — reserved for Phase 2+.

A single WebSocket connection carries STT + LLM + TTS bidirectionally. Only
:meth:`stream` is meaningful; :meth:`invoke` is not supported.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from ..base import ModelInfo, MultimodalAdapter
from ..context import ModelContext
from ..transport import WebSocketTransportMixin


class RealtimeAdapter(MultimodalAdapter, WebSocketTransportMixin):
    """OpenAI Realtime API adapter (STT+LLM+TTS three-in-one event stream)."""

    modality = "realtime"
    factory = "openai"

    def __init__(self, context: ModelContext) -> None:
        MultimodalAdapter.__init__(self, context)
        WebSocketTransportMixin.__init__(
            self,
            ws_url=context.extra.get("ws_url"),
            auth_headers=context.extra.get("auth_headers"),
        )

    def _build_inner(self) -> None:
        # No existing SDK class for Realtime yet; left as a Phase 2 deliverable.
        raise NotImplementedError("RealtimeAdapter._build_inner is a Phase 2 deliverable")

    async def invoke(self, request: Any) -> Any:
        raise NotImplementedError("Realtime uses stream(), not invoke()")

    async def stream(self, request: Any) -> AsyncIterator[Any]:
        raise NotImplementedError("RealtimeAdapter streaming is a Phase 2 deliverable")

    async def health_check(self) -> bool:
        return self._ws_url is not None

    def get_model_info(self) -> ModelInfo:
        return ModelInfo(
            model_id=self._context.model_name,
            display_name=self._context.display_name or "",
            provider=self.factory,
            capabilities={"realtime": True, "audio": True},
        )

"""Modality-specific construction contexts for the gateway.

The historical ``ModelContext`` was a single 20-field dataclass consolidating
every modality's construction params (LLM/VLM observer+model_id; Embedding
dim+model_type; Rerank name+url; STT/TTS Config+audio path; LongContext
max_context_tokens+truncation_strategy). Passing ``temperature`` to an STT
build, or ``speed_ratio`` to an LLM, silently landed in ``extra`` and was
ignored — no error, no signal.

This module splits that monolith into a slim :class:`ModelContext` base +
modality subclasses (``LLMContext`` / ``VLMContext`` / ``EmbeddingContext`` /
``STTContext`` / ``TTSContext``), each declaring only the fields its modality
reads. The LLM/VLM sampling params and the WS endpoint — previously untyped
keys in ``extra`` — are promoted to typed sub-objects (:class:`LLMSampling`,
:class:`WSTransport`). Constructing a context via :func:`build_context` returns
the subclass for its modality, so reading ``context.sampling.temperature`` on
an STT context raises ``AttributeError`` rather than silently no-opping.

``modality`` / ``factory`` / ``tenant_id`` / ``slot`` are gateway-dispatch and
cache-key concerns, read only by :class:`MultimodalGateway`; they stay on the
base. ``observer`` is cross-cutting (LLM/VLM *and* ModelEngine STT/TTS wrap
:class:`OpenAIModel`), so it too stays on the base. ``timeout_seconds`` — the
single most-used ``extra`` key, read by every HTTP-backed adapter — is promoted
to a base field.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class LLMSampling:
    """LLM / VLM sampling parameters (the typed replacement for ``extra`` keys).

    All fields default to ``None`` meaning "unset — let the wrapped model use
    its own default". A field that is genuinely optional for one modality and
    unused by another (e.g. ``truncation_strategy`` is LongContext-only,
    ``frequency_penalty`` is VLM-only) simply stays ``None`` for the other.

    Attributes:
        temperature: Sampling temperature.
        top_p: Nucleus-sampling probability mass.
        stream: Whether to stream the response.
        max_output_tokens: Cap on generated tokens (LLM / LongContext).
        max_tokens: VLM generation cap, or LongContext context-window size.
        truncation_strategy: LongContext context-truncation strategy.
        frequency_penalty: VLM frequency penalty (set as a dead instance
            attribute on the wrapped model, never forwarded to the wire).
        extra_body: Extra request-body fields forwarded to ``OpenAIModel``.
    """

    temperature: Optional[float] = None
    top_p: Optional[float] = None
    stream: Optional[bool] = None
    max_output_tokens: Optional[int] = None
    max_tokens: Optional[int] = None
    truncation_strategy: Optional[str] = None
    frequency_penalty: Optional[float] = None
    extra_body: Optional[dict] = None


@dataclass
class WSTransport:
    """WebSocket endpoint for the WS-backed STT/TTS variants.

    Attributes:
        ws_url: The WebSocket endpoint URL.
        auth_headers: Optional auth headers sent on connect (``None`` → ``{}``
            by the transport mixin; currently never configured in production).
    """

    ws_url: Optional[str] = None
    auth_headers: Optional[dict] = None


@dataclass
class ModelContext:
    """Slim base construction context — 通用 + cross-cutting + residual.

    ``modality`` is the capability family: ``llm`` | ``llm_long_context`` |
    ``vlm`` | ``stt`` | ``tts`` | ``embedding`` | ``multi_embedding`` |
    ``rerank``. ``factory`` is the normalized provider name (``openai`` |
    ``ali`` | ``volc`` | ``jina`` | ``siliconflow`` | ``dashscope`` |
    ``cohere`` | ``modelengine`` | ...). ``slot`` mirrors
    ``MODEL_CONFIG_MAPPING`` keys so the gateway can distinguish VLM slots.

    Attributes:
        model_name: Provider model identifier passed to the API.
        base_url: HTTP or WebSocket endpoint base URL.
        api_key: Authorization credential.
        modality: Capability family (see above).
        factory: Normalized provider name (see above).
        tenant_id: Optional tenant scope.
        slot: Optional config-mapping slot key; disambiguates VLM slots.
        ssl_verify: Whether to verify TLS certificates.
        display_name: Optional human-readable label.
        observer: Optional smolagents Observer — cross-cutting; read by any
            adapter that wraps :class:`OpenAIModel` (LLM, VLM, ModelEngine
            STT/TTS).
        timeout_seconds: HTTP request timeout (read by every HTTP-backed
            adapter and forwarded to ``OpenAIModel``).
        extra: Residual vendor-protocol-specific keys (WS STT/TTS ``format`` /
            ``rate`` / ``enable_vad`` / ``timeout`` / ``resourceid`` /
            ``sample_rate`` / ``voice_type``). These are genuinely per-vendor
            and never configured in production; they stay a dict rather than
            being typed into vendor subclasses (vendor is encoded at registry
            dispatch, not in the context).
    """

    # ---- 通用 ----
    model_name: str
    base_url: str
    api_key: str
    modality: str
    factory: str
    tenant_id: Optional[str] = None
    slot: Optional[str] = None
    ssl_verify: bool = True
    display_name: Optional[str] = None

    # ---- cross-cutting ----
    observer: Any = None
    timeout_seconds: Optional[float] = None

    # ---- residual vendor-protocol keys ----
    extra: Dict[str, Any] = field(default_factory=dict)

    def cache_key(self) -> tuple:
        """Returns a stable identity for adapter instance caching.

        Returns:
            A tuple of ``(tenant_id, modality, slot, model_name, factory)``.
        """
        return (
            self.tenant_id or "",
            self.modality,
            self.slot or "",
            self.model_name,
            self.factory,
        )


@dataclass
class LLMContext(ModelContext):
    """Construction context for ``llm`` and ``llm_long_context``.

    Attributes:
        sampling: LLM sampling parameters (temperature / top_p / stream /
            max_output_tokens / max_tokens / truncation_strategy / extra_body).
    """

    sampling: Optional[LLMSampling] = None


@dataclass
class VLMContext(ModelContext):
    """Construction context for ``vlm``.

    Attributes:
        sampling: VLM sampling parameters (temperature / top_p / max_tokens /
            frequency_penalty).
        capabilities: Per-capability overrides; only the ``"audio"`` key is
            consulted (VLM is the only adapter that reads capabilities).
    """

    sampling: Optional[LLMSampling] = None
    capabilities: Dict[str, bool] = field(default_factory=dict)


@dataclass
class EmbeddingContext(ModelContext):
    """Construction context for ``embedding`` / ``multi_embedding``.

    Attributes:
        embedding_dim: Embedding vector dimension (vestigial in the gateway
            path — set by the bridge / ``memory.embedding_model`` but read by
            no gateway adapter; kept to preserve construction sites).
        model_type: ``"embedding"`` | ``"multi_embedding"`` (vestigial in the
            gateway path; see ``embedding_dim``).
    """

    embedding_dim: Optional[int] = None
    model_type: Optional[str] = None


@dataclass
class STTContext(ModelContext):
    """Construction context for ``stt``.

    A union of WS-vendor (Ali/Volc) and HTTP-vendor (ModelEngine) fields:
    ModelEngine STT ignores ``language`` / ``audio_file_path`` / ``ws`` /
    ``model_appid`` / ``access_token``; Ali/Volc ignore ``timeout_seconds``.
    The bleed is Optional-and-ignored, not erroneous. Vendor is encoded at
    registry dispatch, so there are no vendor subclasses.

    Attributes:
        language: STT language code (default ``"zh"``).
        audio_file_path: Optional STT audio file path (WS variants).
        model_appid: Volc STT app id (ignored by Ali / ModelEngine).
        access_token: Volc STT access token (ignored by Ali / ModelEngine).
        ws: WebSocket transport (WS variants; ``None`` for ModelEngine).
    """

    language: str = "zh"
    audio_file_path: Optional[str] = None
    model_appid: Optional[str] = None
    access_token: Optional[str] = None
    ws: Optional[WSTransport] = None


@dataclass
class TTSContext(ModelContext):
    """Construction context for ``tts``.

    Same WS-vs-HTTP union shape as :class:`STTContext`.

    Attributes:
        speed_ratio: TTS speech-rate multiplier.
        voice: Optional TTS voice id.
        audio_file_path: Optional TTS audio file path (WS variants).
        model_appid: Volc TTS app id (ignored by Ali / ModelEngine).
        access_token: Volc TTS access token (ignored by Ali / ModelEngine).
        ws: WebSocket transport (WS variants; ``None`` for ModelEngine).
    """

    speed_ratio: float = 1.0
    voice: Optional[str] = None
    audio_file_path: Optional[str] = None
    model_appid: Optional[str] = None
    access_token: Optional[str] = None
    ws: Optional[WSTransport] = None


_SUBCLASS_FOR: Dict[str, type] = {
    "llm": LLMContext,
    "llm_long_context": LLMContext,
    "vlm": VLMContext,
    "embedding": EmbeddingContext,
    "multi_embedding": EmbeddingContext,
    "stt": STTContext,
    "tts": TTSContext,
}


def build_context(
    modality: str,
    *,
    model_name: str,
    base_url: str,
    api_key: str,
    factory: str,
    **kwargs: Any,
) -> ModelContext:
    """Construct the modality-specific :class:`ModelContext` subclass.

    The single source of subclass selection: the bridge
    (:func:`backend.services.model_gateway_service._config_to_context`),
    ``sdk.nexent.memory.embedding_model``, and tests all go through here, so
    the gateway's :meth:`MultimodalGateway.get_adapter` receives a context
    already typed for its modality. Unknown keyword arguments raise
    ``TypeError`` at construction time (e.g. passing ``language=`` to an LLM
    context, or ``sampling=`` to an STT context) — the runtime safety this
    refactor adds.

    Args:
        modality: Capability family (selects the subclass).
        model_name: Provider model identifier.
        base_url: HTTP or WebSocket endpoint base URL.
        api_key: Authorization credential.
        factory: Normalized provider name.
        **kwargs: Subclass-specific fields (``sampling`` / ``ws`` /
            ``language`` / ``speed_ratio`` / ``embedding_dim`` / ...).

    Returns:
        The modality-specific :class:`ModelContext` subclass instance.
    """
    cls = _SUBCLASS_FOR.get(modality, ModelContext)
    return cls(
        model_name=model_name,
        base_url=base_url,
        api_key=api_key,
        modality=modality,
        factory=factory,
        **kwargs,
    )

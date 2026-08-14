"""Modality adapter aggregation layer.

This is the single place that re-exports the public adapter API and triggers
built-in adapter registration: importing :mod:`nexent.core.gateway.modality`
imports every built-in adapter module, whose ``@register_adapter`` decorators
populate the process-wide :class:`AdapterRegistry`.

Modality subpackages (``llm`` / ``vlm`` / ``stt`` / ``tts`` / ``embedding`` /
``rerank``) are namespace packages on purpose: they ship no ``__init__.py`` so
this module stays the single aggregation point. Import concrete classes via
this layer or via their leaf module (``modality.vlm.openai``).

This is the **base branch**: no adapters are registered yet, so the registry is
empty. Each feature branch (``feat/gw-vlm``, ``-llm``, …) appends its modality's
import lines here, which registers that modality's adapters.
"""

__all__: list[str] = []

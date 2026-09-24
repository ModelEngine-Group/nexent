"""Process-local model loading for data processing.

The SDK deliberately receives model configuration from its caller.  It does not
read Nexent environment variables; the backend parser runtime owns that
configuration boundary.
"""

import os
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


class ModelRegistry:
    """Lazy, process-local registry for the supported extraction models."""

    SUPPORTED_ALIASES = {"unstructured_default", "table_transformer"}

    def __init__(self, model_paths: Optional[Dict[str, Optional[str]]] = None):
        self.model_paths = dict(model_paths or {})
        self._models: Dict[str, Any] = {}

    def validate_aliases(self, aliases: Iterable[str]) -> list[str]:
        normalized: list[str] = []
        for alias in aliases:
            value = (alias or "").strip()
            if not value:
                continue
            if value not in self.SUPPORTED_ALIASES:
                raise ValueError(
                    f"Unsupported data-process preload model alias: {value}. "
                    f"Supported aliases: {', '.join(sorted(self.SUPPORTED_ALIASES))}"
                )
            if value not in normalized:
                normalized.append(value)
        return normalized

    def preload(self, aliases: Iterable[str]) -> Dict[str, Any]:
        """Load each requested alias and return the process-local handles."""
        loaded: Dict[str, Any] = {}
        for alias in self.validate_aliases(aliases):
            loaded[alias] = self.get(alias)
        return loaded

    def get(self, alias: str) -> Any:
        """Return a cached model, loading it once in this process if needed."""
        if alias not in self.SUPPORTED_ALIASES:
            raise ValueError(f"Unsupported data-process model alias: {alias}")
        if alias not in self._models:
            loader = getattr(self, f"_load_{alias}")
            self._models[alias] = loader()
        return self._models[alias]

    def _load_unstructured_default(self) -> Any:
        model_path = self._normalize_path(self.model_paths.get("unstructured_default"))
        if model_path:
            os.environ["UNSTRUCTURED_DEFAULT_MODEL_INITIALIZE_PARAMS_JSON_PATH"] = model_path

        # The third-party loader owns its singleton cache.  Import it only when
        # a parser child explicitly preloads or first needs this model.
        from unstructured_inference.models.base import get_model

        return get_model()

    def _load_table_transformer(self) -> Any:
        model_path = self._normalize_path(self.model_paths.get("table_transformer"))
        if not model_path:
            raise ValueError("TABLE_TRANSFORMER_MODEL_PATH is not configured")

        from . import extract_image

        extract_image.TABLE_TRANSFORMER_MODEL_PATH = model_path
        agent = extract_image.get_tables_agent()
        extract_image.custom_load_table_model()
        return agent

    @staticmethod
    def _normalize_path(path_value: Optional[str]) -> Optional[str]:
        if not path_value:
            return None
        candidate = Path(path_value)
        if not candidate.exists():
            raise FileNotFoundError(f"Model path does not exist: {candidate}")
        return os.fspath(candidate)

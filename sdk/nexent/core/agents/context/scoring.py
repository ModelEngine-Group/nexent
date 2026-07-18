"""MMR scoring with external, local-CPU, and model-free fallbacks."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Protocol, Sequence

from .models import ContextItem


logger = logging.getLogger("context_scoring")


class EmbeddingProvider(Protocol):
    """Narrow embedding dependency injected into the SDK context domain."""

    @property
    def fingerprint(self) -> str: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class ExternalEmbeddingProvider:
    """Adapter for Nexent's existing BaseEmbedding-compatible models."""

    def __init__(self, model: object) -> None:
        self._model = model

    @property
    def fingerprint(self) -> str:
        name = getattr(
            self._model,
            "embedding_model_name",
            getattr(self._model, "model", self._model.__class__.__name__),
        )
        return f"external:{name}"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        values = self._model.get_embeddings(list(texts))
        return [[float(component) for component in vector] for vector in values]


class CpuEmbeddingProvider:
    """Lazy local transformers encoder that never downloads model weights."""

    def __init__(self, model_path: str, *, max_length: int = 512) -> None:
        self.model_path = model_path
        self.max_length = max_length
        self._tokenizer = None
        self._model = None

    @property
    def fingerprint(self) -> str:
        return f"cpu:{self.model_path}:{self.max_length}"

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoModel, AutoTokenizer

        self._tokenizer = AutoTokenizer.from_pretrained(
            self.model_path,
            local_files_only=True,
        )
        self._model = AutoModel.from_pretrained(
            self.model_path,
            local_files_only=True,
        ).to("cpu")
        self._model.eval()
        torch.set_grad_enabled(False)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        import torch

        self._load()
        encoded = self._tokenizer(
            list(texts),
            padding=True,
            truncation=True,
            max_length=self.max_length,
            return_tensors="pt",
        )
        with torch.inference_mode():
            hidden = self._model(**encoded).last_hidden_state
        mask = encoded["attention_mask"].unsqueeze(-1).to(hidden.dtype)
        pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
        normalized = torch.nn.functional.normalize(pooled, p=2, dim=1)
        return normalized.cpu().tolist()


@dataclass(frozen=True)
class EmbeddingBatch:
    vectors: tuple[tuple[float, ...], ...] | None
    mode: str
    provider_fingerprint: str | None = None
    failures: tuple[str, ...] = ()


class EmbeddingProviderChain:
    """Try external > local CPU > no-model, including runtime failures."""

    def __init__(
        self,
        *,
        external: EmbeddingProvider | None = None,
        cpu: EmbeddingProvider | None = None,
    ) -> None:
        self.external = external
        self.cpu = cpu

    def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
        failures: list[str] = []
        for mode, provider in (("external", self.external), ("cpu", self.cpu)):
            if provider is None:
                continue
            try:
                vectors = provider.embed(texts)
                _validate_vectors(vectors, len(texts))
                return EmbeddingBatch(
                    vectors=tuple(tuple(vector) for vector in vectors),
                    mode=mode,
                    provider_fingerprint=provider.fingerprint,
                    failures=tuple(failures),
                )
            except Exception as exc:  # fallback is a required availability feature
                failure = f"{mode}:{exc.__class__.__name__}"
                failures.append(failure)
                logger.warning("Context embedding provider failed; falling back (%s)", failure)
        return EmbeddingBatch(vectors=None, mode="none", failures=tuple(failures))


@dataclass(frozen=True)
class ScoredItem:
    item: ContextItem
    relevance: float
    marginal_relevance: float
    selection_rank: int


@dataclass(frozen=True)
class MMRResult:
    scored_items: tuple[ScoredItem, ...]
    embedding_mode: str
    provider_fingerprint: str | None
    embedding_failures: tuple[str, ...]


def rank_by_mmr(
    items: Sequence[ContextItem],
    *,
    intent: str,
    providers: EmbeddingProviderChain | None = None,
    lambda_value: float = 0.7,
) -> MMRResult:
    """Greedily rank optional items by maximal marginal relevance."""

    if not 0 <= lambda_value <= 1:
        raise ValueError("MMR lambda must be between 0 and 1")
    if any(item.required for item in items):
        raise ValueError("required context items must not enter MMR scoring")
    if not items:
        return MMRResult((), "none", None, ())

    texts = [intent, *(_item_text(item) for item in items)]
    batch = (providers or EmbeddingProviderChain()).embed(texts)
    if batch.vectors is None:
        relevances = [item.score() for item in items]
        item_vectors = None
    else:
        query_vector = batch.vectors[0]
        item_vectors = batch.vectors[1:]
        relevances = [_cosine(query_vector, vector) for vector in item_vectors]

    remaining = list(range(len(items)))
    selected: list[int] = []
    ranked: list[ScoredItem] = []
    while remaining:
        candidates: list[tuple[float, float, int, str, int]] = []
        for index in remaining:
            redundancy = 0.0
            if selected:
                if item_vectors is None:
                    redundancy = max(
                        1.0 if items[index].content_fingerprint == items[chosen].content_fingerprint else 0.0
                        for chosen in selected
                    )
                else:
                    redundancy = max(
                        _cosine(item_vectors[index], item_vectors[chosen])
                        for chosen in selected
                    )
            marginal = lambda_value * relevances[index] - (1 - lambda_value) * redundancy
            candidates.append((marginal, relevances[index], items[index].priority, items[index].id, index))
        _, relevance, _, _, chosen = max(
            candidates,
            key=lambda value: (value[0], value[1], value[2], _reverse_text_key(value[3])),
        )
        redundancy = 0.0
        if selected:
            if item_vectors is None:
                redundancy = max(
                    1.0 if items[chosen].content_fingerprint == items[index].content_fingerprint else 0.0
                    for index in selected
                )
            else:
                redundancy = max(
                    _cosine(item_vectors[chosen], item_vectors[index]) for index in selected
                )
        marginal = lambda_value * relevance - (1 - lambda_value) * redundancy
        ranked.append(ScoredItem(items[chosen], relevance, marginal, len(ranked)))
        selected.append(chosen)
        remaining.remove(chosen)

    return MMRResult(
        scored_items=tuple(ranked),
        embedding_mode=batch.mode,
        provider_fingerprint=batch.provider_fingerprint,
        embedding_failures=batch.failures,
    )


def _item_text(item: ContextItem) -> str:
    import json

    return json.dumps(item.content, ensure_ascii=False, sort_keys=True, default=str)


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return max(-1.0, min(1.0, numerator / (left_norm * right_norm)))


def _validate_vectors(vectors: Sequence[Sequence[float]], expected: int) -> None:
    if len(vectors) != expected or not vectors:
        raise ValueError("embedding provider returned an unexpected vector count")
    dimension = len(vectors[0])
    if dimension <= 0 or any(len(vector) != dimension for vector in vectors):
        raise ValueError("embedding provider returned inconsistent vector dimensions")


def _reverse_text_key(value: str) -> tuple[int, ...]:
    """Make lexicographically smaller IDs win a max() tie deterministically."""

    return tuple(-ord(character) for character in value)

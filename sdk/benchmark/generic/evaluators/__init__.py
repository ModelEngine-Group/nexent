# -*- coding: utf-8 -*-
"""Pluggable evaluator registry for generic benchmarks.

Each evaluator module exports one or more functions compatible with
Langfuse's EvaluatorFunction protocol:

    def my_evaluator(*, input, output, expected_output, metadata, **kwargs):
        return Evaluation(name="metric", value=0.95)

Register evaluators here so run_experiment.py can resolve them by name.
"""
from typing import Callable, Dict, List

from .em_f1 import em_evaluator, f1_evaluator
from .exact_match import exact_match_evaluator
from .gaia_exact_match import gaia_exact_match_evaluator
from .gaia_final_answer import gaia_final_answer_evaluator
from .keyword_match import keyword_match_evaluator
from .numeric_answer import numeric_answer_evaluator


# Registry: name -> evaluator function
EVALUATOR_REGISTRY: Dict[str, Callable] = {
    "exact_match": exact_match_evaluator,
    "gaia_exact_match": gaia_exact_match_evaluator,
    "gaia_final_answer": gaia_final_answer_evaluator,
    "em": em_evaluator,
    "f1": f1_evaluator,
    "keyword_match": keyword_match_evaluator,
    "numeric_answer": numeric_answer_evaluator,
}


def resolve_evaluators(names: List[str]) -> List[Callable]:
    """Resolve evaluator names to functions.

    Args:
        names: List of evaluator names from the registry.

    Returns:
        List of evaluator functions.

    Raises:
        ValueError: If an unknown evaluator name is provided.
    """
    resolved = []
    for name in names:
        if name not in EVALUATOR_REGISTRY:
            available = ", ".join(sorted(EVALUATOR_REGISTRY.keys()))
            raise ValueError(
                f"Unknown evaluator '{name}'. Available: {available}"
            )
        resolved.append(EVALUATOR_REGISTRY[name])
    return resolved


def list_evaluators() -> List[str]:
    """Return sorted list of available evaluator names."""
    return sorted(EVALUATOR_REGISTRY.keys())

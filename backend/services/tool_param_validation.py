"""Centralized value-range constraints for user-configurable tool parameters.

Single source of truth shared by the /tool/update save path and the
/tool/validate test-panel path. Keeping the table here (instead of scattering
checks across tool classes) makes the allowed range for any parameter
reviewable in one place.

Only present-but-invalid values are rejected: missing keys are skipped because
the SDK tool constructors fill in defaults at instantiation time. A config
that would otherwise work is never rejected here.

Raises:
    ValidationError: with a message shaped like the existing aidp_search
        kds_list check, e.g.
        "knowledge_base_search.top_k must be between 1 and 100, got: 200"
"""

from dataclasses import dataclass
from typing import Any, Dict

from consts.exceptions import ValidationError


# ---- Constraint kinds -----------------------------------------------------


@dataclass
class IntRange:
    """Integer parameter restricted to [min, max]."""

    min: int = 1
    max: int = 100


@dataclass
class FloatRange:
    """Float parameter restricted to [min, max]."""

    min: float = 0.0
    max: float = 1.0


@dataclass
class PortRange:
    """TCP/UDP port number restricted to [1, 65535]."""

    min: int = 1
    max: int = 65535


@dataclass
class EnumValues:
    """Parameter restricted to one of the allowed string values."""

    allowed: tuple


@dataclass
class NonEmpty:
    """Parameter must hold a non-empty value (None/""/"[]"/[] rejected)."""

    pass


# ---- Constraint table -----------------------------------------------------
# tool_name -> {param_name: constraint}

TOOL_PARAM_CONSTRAINTS: Dict[str, Dict[str, Any]] = {
    "knowledge_base_search": {
        "top_k": IntRange(min=1, max=100),
        "search_mode": EnumValues(allowed=("hybrid", "accurate", "semantic")),
    },
    "dify_search": {
        "top_k": IntRange(min=1, max=100),
        "search_method": EnumValues(
            allowed=(
                "keyword_search",
                "semantic_search",
                "full_text_search",
                "hybrid_search",
            )
        ),
    },
    "datamate_search": {
        "top_k": IntRange(min=1, max=100),
        "threshold": FloatRange(min=0.0, max=1.0),
        "kb_page": IntRange(min=1, max=10_000),
        "kb_page_size": IntRange(min=1, max=100),
    },
    "haotian_search": {
        "top_k": IntRange(min=1, max=100),
        "keyword_weight": FloatRange(min=0.0, max=1.0),
        "vector_weight": FloatRange(min=0.0, max=1.0),
    },
    "ragflow_search": {
        # dataset_ids has a "[]" default in the SDK (-> optional in schema) but
        # the SDK constructor raises on an empty selection, so it must be
        # non-empty at save time.
        "dataset_ids": NonEmpty(),
        "top_k": IntRange(min=1, max=100),
        "similarity_threshold": FloatRange(min=0.0, max=1.0),
        "vector_similarity_weight": FloatRange(min=0.0, max=1.0),
    },
    "idata_search": {
        "top_k": IntRange(min=1, max=100),
        # -10.0 is the SDK default sentinel for "threshold disabled"; keep it
        # legal while still capping the upper bound.
        "similarity_threshold": FloatRange(min=-10.0, max=1.0),
        "keyword_similarity_weight": FloatRange(min=0.0, max=1.0),
        "vector_similarity_weight": FloatRange(min=0.0, max=1.0),
    },
    "tavily_search": {"max_results": IntRange(min=1, max=100)},
    "exa_search": {"max_results": IntRange(min=1, max=100)},
    "linkup_search": {"max_results": IntRange(min=1, max=100)},
    "terminal": {"ssh_port": PortRange()},
    "get_email": {"timeout": IntRange(min=1, max=600)},
}

# Map SDK class names back to their user-facing tool names so callers that only
# hold a class_name (e.g. "KnowledgeBaseSearchTool") can validate too.
CLASS_NAME_TO_TOOL_NAME: Dict[str, str] = {
    "KnowledgeBaseSearchTool": "knowledge_base_search",
    "DifySearchTool": "dify_search",
    "DataMateSearchTool": "datamate_search",
    "HaotianSearchTool": "haotian_search",
    "RAGFlowSearchTool": "ragflow_search",
    "IdataSearchTool": "idata_search",
    "TavilySearchTool": "tavily_search",
    "ExaSearchTool": "exa_search",
    "LinkupSearchTool": "linkup_search",
    "TerminalTool": "terminal",
    "GetEmailTool": "get_email",
}


# ---- Validation -----------------------------------------------------------


def validate_tool_params(tool_name: str, params: Dict[str, Any]) -> None:
    """Validate ``params`` against the constraint table for ``tool_name``.

    Args:
        tool_name: User-facing tool name (e.g. "dify_search"). A class name is
            normalized through ``CLASS_NAME_TO_TOOL_NAME`` when supplied.
        params: The parameter dict being saved or tested.

    Raises:
        ValidationError: if a present value violates its constraint.
    """
    name = CLASS_NAME_TO_TOOL_NAME.get(tool_name, tool_name)
    constraints = TOOL_PARAM_CONSTRAINTS.get(name)
    if not constraints:
        return

    for param_name, constraint in constraints.items():
        if param_name not in params:
            # Key absent -> the SDK constructor fills in its default.
            continue
        if params[param_name] is None:
            # Optional-with-default params are treated as required on save: a
            # cleared value must not be persisted / passed to validation.
            raise ValidationError(
                f"{name}.{param_name} is required and must not be empty"
            )
        _validate_one(name, param_name, params[param_name], constraint)


def _validate_one(tool_name: str, param_name: str, value: Any, constraint: Any) -> None:
    prefix = f"{tool_name}.{param_name}"

    if isinstance(constraint, IntRange):
        if not _is_int(value):
            raise ValidationError(
                f"{prefix} must be an integer between {constraint.min} and "
                f"{constraint.max}, got: {value}"
            )
        if not constraint.min <= value <= constraint.max:
            raise ValidationError(
                f"{prefix} must be between {constraint.min} and {constraint.max}, "
                f"got: {value}"
            )
    elif isinstance(constraint, FloatRange):
        if not _is_number(value):
            raise ValidationError(
                f"{prefix} must be a number between {constraint.min} and "
                f"{constraint.max}, got: {value}"
            )
        if not constraint.min <= value <= constraint.max:
            raise ValidationError(
                f"{prefix} must be between {constraint.min} and {constraint.max}, "
                f"got: {value}"
            )
    elif isinstance(constraint, PortRange):
        if not _is_int(value) or not constraint.min <= value <= constraint.max:
            raise ValidationError(
                f"{prefix} must be a port between {constraint.min} and "
                f"{constraint.max}, got: {value}"
            )
    elif isinstance(constraint, EnumValues):
        if value not in constraint.allowed:
            raise ValidationError(
                f"{prefix} is required; allowed values: "
                f"{', '.join(constraint.allowed)}, got: {value}"
            )
    elif isinstance(constraint, NonEmpty):
        if _is_empty(value):
            raise ValidationError(
                f"{prefix} is required and must not be empty, got: {value!r}"
            )


def _is_int(value: Any) -> bool:
    # bool is an int subclass; True/False are not valid integer params.
    if isinstance(value, bool):
        return False
    # Accept whole floats (e.g. 3.0) so a JSON-decoded 3.0 is not rejected.
    if isinstance(value, int):
        return True
    return isinstance(value, float) and value.is_integer()


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        stripped = value.strip()
        return stripped == "" or stripped == "[]"
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) == 0
    return False

"""
Numeric range constraints for local tool parameters.

Keyed by tool name; each entry is {param_name: (type, min, max)} where
min/max may be None to indicate an unbounded side. These are enforced on
the backend (service layer) before persisting tool configuration, while the
SDK constructors apply the same normalization at runtime as a defense-in-depth
fallback for legacy/errored data.

Keep in sync with the matching ``Field(...)`` declarations in the SDK tools
under ``sdk/nexent/core/tools/``.
"""

TOOL_PARAM_RANGE_CONSTRAINTS = {
    "knowledge_base_search": {"top_k": ("int", 1, 100)},
    "dify_search": {"top_k": ("int", 1, 100)},
    "datamate_search": {
        "top_k": ("int", 1, 100),
        "threshold": ("float", 0.0, 1.0),
        "kb_page": ("int", 1, None),
        "kb_page_size": ("int", 1, 100),
    },
    "haotian_search": {
        "top_k": ("int", 1, 100),
        "keyword_weight": ("float", 0.0, 1.0),
        "vector_weight": ("float", 0.0, 1.0),
    },
    "ragflow_search": {
        "top_k": ("int", 1, 100),
        "similarity_threshold": ("float", 0.0, 1.0),
        "vector_similarity_weight": ("float", 0.0, 1.0),
    },
    "idata_search": {
        "top_k": ("int", 1, 100),
        "similarity_threshold": ("float", None, 1.0),
        "keyword_similarity_weight": ("float", 0.0, 1.0),
        "vector_similarity_weight": ("float", 0.0, 1.0),
    },
    "tavily_search": {"max_results": ("int", 1, 100)},
    "exa_search": {"max_results": ("int", 1, 100)},
    "linkup_search": {"max_results": ("int", 1, 100)},
    "terminal": {"ssh_port": ("int", 1, 65535)},
    "get_email": {"timeout": ("int", 1, None)},
}

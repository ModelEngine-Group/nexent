# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Serializable catalog metadata for the Runtime-owned knowledge tool."""

import json

from contracts.tool import ToolInfo


def knowledge_tool_info():
    return ToolInfo(
        name="knowledge_base_search", class_name="KnowledgeBaseSearchTool", source="local", usage=None,
        origin_name="knowledge_base_search", category="search", is_user_selectable=False, output_type="string",
        description=("Performs a local knowledge base search based on your query then returns the top search results. "
                     "A tool for retrieving domain-specific knowledge, documents, and information stored in the local knowledge base. "
                     "Use this tool when users ask questions related to specialized knowledge, technical documentation, "
                     "domain expertise, personal notes, or any information that has been indexed in the knowledge base. "
                     "Suitable for queries requiring access to stored knowledge that may not be publicly available."),
        description_zh="执行本地知识库检索并返回最相关的结果。",
        inputs=json.dumps({
            "query": {"type": "string", "description": "The search query to perform.", "description_zh": "要执行的搜索查询词"},
            "index_names": {"type": "array", "description": "The list of index names to search",
                            "description_zh": "要索引的知识库", "nullable": True},
        }, ensure_ascii=False),
        params=[
            {"name": "top_k", "type": "integer", "description": "Maximum number of search results", "default": 3,
             "optional": True, "constraints": {"ge": 1, "le": 100}},
            {"name": "index_names", "type": "array", "description": "The list of index names to search", "optional": False},
            {"name": "search_mode", "type": "string", "description": "Search mode: hybrid, accurate, semantic",
             "default": "hybrid", "optional": True},
            {"name": "rerank", "type": "boolean", "description": "Whether to enable reranking", "default": False, "optional": True},
            {"name": "rerank_model_name", "type": "string", "description": "The rerank model name", "default": "", "optional": True},
        ],
    )

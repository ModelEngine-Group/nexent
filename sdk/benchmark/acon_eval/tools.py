"""ACON QA benchmark tools for nexent agent.

Provides WikipediaSearchTool and FinalAnswerTool as smolagents.Tool
subclasses, plus a helper to register them in nexent's tool namespace
so that NexentAgent.create_local_tool() can find them via globals().
"""
from typing import Any

import requests
from smolagents.tools import Tool

from nexent.core.agents.agent_model import ToolConfig


class WikipediaSearchTool(Tool):
    name = "wikipedia_search"
    description = (
        "Uses semantic search to retrieve the parts of 2018 wikipedia "
        "that could be most relevant to answer your query."
    )
    inputs = {
        "query": {
            "type": "string",
            "description": (
                "The query to perform. This should be semantically close to "
                "your target documents. Use the affirmative form rather than "
                "a question."
            ),
        },
        "n_results": {
            "type": "integer",
            "nullable": True,
            "description": "The number of results to return. Minimum is 3. Maximum is 10.",
        },
    }
    output_type = "string"

    def __init__(self, port: str = "8005", **kwargs):
        super().__init__()
        self.port = port
        self.url = f"http://127.0.0.1:{self.port}/retrieve"

    def forward(self, query: str, n_results: int = 3) -> str:
        if n_results < 3:
            n_results = 3
        if n_results > 10:
            n_results = 10

        assert isinstance(query, str), "Your search query must be a string"
        payload = {
            "queries": [query],
            "topk": n_results,
            "return_scores": True,
        }

        response = requests.post(self.url, json=payload)
        response.raise_for_status()

        retrieved_data = response.json()
        docs = retrieved_data["result"][0]

        return "Retrieved documents:" + "".join(
            f"\n\n[Document {str(i)}]\n" + doc["document"]["contents"]
            for i, doc in enumerate(docs)
        )


class FinalAnswerTool(Tool):
    name = "final_answer"
    description = "Provides a final answer to the given problem."
    inputs = {
        "answer": {
            "type": "any",
            "description": "The final answer to the problem",
        },
    }
    output_type = "any"

    def forward(self, answer: Any) -> Any:
        return answer


# ---------------------------------------------------------------------------
# Tool registration and ToolConfig builders
# ---------------------------------------------------------------------------

def register_acon_tools():
    """Inject ACON tool classes into nexent.core.tools AND nexent_agent namespaces.

    NexentAgent.create_local_tool() looks up tool classes via globals(),
    which is populated by `from ..tools import *` at import time.
    Since `setattr` on the tools module does NOT update nexent_agent's
    already-executed `globals()`, we must inject into BOTH modules.
    """
    import nexent.core.tools as _tools_mod
    import nexent.core.agents.nexent_agent as _agent_mod
    for cls in (WikipediaSearchTool, FinalAnswerTool):
        setattr(_tools_mod, cls.__name__, cls)
        setattr(_agent_mod, cls.__name__, cls)


def build_wikipedia_search_tool_config(port: str = "8005") -> ToolConfig:
    return ToolConfig(
        class_name="WikipediaSearchTool",
        name="wikipedia_search",
        description=WikipediaSearchTool.description,
        inputs=str(WikipediaSearchTool.inputs),
        output_type=WikipediaSearchTool.output_type,
        params={"port": port},
        source="local",
    )


def build_final_answer_tool_config() -> ToolConfig:
    return ToolConfig(
        class_name="FinalAnswerTool",
        name="final_answer",
        description=FinalAnswerTool.description,
        inputs=str(FinalAnswerTool.inputs),
        output_type=FinalAnswerTool.output_type,
        params={},
        source="local",
    )


def get_acon_tool_configs(port: str = "8005") -> list[ToolConfig]:
    """Return the standard ACON QA tool config list."""
    return [
        build_wikipedia_search_tool_config(port=port),
        build_final_answer_tool_config(),
    ]
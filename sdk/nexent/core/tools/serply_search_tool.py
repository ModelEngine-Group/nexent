import json
import logging

import httpx
from pydantic import Field
from smolagents.tools import Tool

from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import SearchResultTextMessage, ToolCategory, ToolSign


# Get logger instance
logger = logging.getLogger("serply_search_tool")

SERPLY_SEARCH_ENDPOINT = "https://api.serply.io/v1/search/"


class SerplySearchTool(Tool):
    name = "serply_search"
    description = "Performs a internet search based on your query (think a Google search) then returns the top search results. " \
                  "A tool for retrieving publicly available information, news, general knowledge, or non-proprietary data from the internet. " \
                  "Use this for real-time open-domain updates, broad topics, or general knowledge queries"

    description_zh = "基于你的查询词进行互联网搜索，返回最相关的搜索结果。适用于获取公开信息、新闻、通用知识或互联网上的非专有数据。特别适合实时信息更新、广泛话题或通用知识查询。"

    inputs = {
        "query": {
            "type": "string",
            "description": "The search query to perform.",
            "description_zh": "要执行的搜索查询词"
        }
    }

    init_param_descriptions = {
        "serply_api_key": {
            "description": "Serply API key",
            "description_zh": "Serply API 密钥"
        },
        "max_results": {
            "description": "Maximum number of search results",
            "description_zh": "返回搜索结果的最大数量"
        }
    }
    output_type = "string"
    category = ToolCategory.SEARCH.value
    tool_sign = ToolSign.SERPLY_SEARCH.value  # Used to distinguish different index sources in summary

    def __init__(self, serply_api_key: str = Field(description="Serply API key"),
                 observer: MessageObserver = Field(description="Message observer", default=None, exclude=True),
                 max_results: int = Field(description="Maximum number of search results", default=3),
     ):

        super().__init__()

        self.observer = observer
        self.serply_api_key = serply_api_key
        self.max_results = max_results
        self.record_ops = 1  # Used to record sequence number

    def forward(self, query: str) -> str:
        # Perform serply search
        serply_search_result = self._search_serply(query)
        if len(serply_search_result) == 0:
            raise Exception(
                'No results found! Try a less restrictive/shorter query.')

        # Send tool running message
        if self.observer:
            # Tool running chunk is emitted by the SDK tool-call bridge in
            # core_agent.py so it is consistent across direct and code_action
            # invocations. We only emit the search card from inside the tool.
            card_content = [{"icon": "search", "text": query}]
            self.observer.add_message("", ProcessType.CARD, json.dumps(
                card_content, ensure_ascii=False))

        search_results_json = []  # Format search results into a unified structure
        search_results_return = []  # Format for input to the large model
        for index, single_result in enumerate(serply_search_result):
            search_result_message = SearchResultTextMessage(
                title=single_result.get("title", ""),
                url=single_result.get("link", ""),
                text=single_result.get("description", ""),
                published_date="",
                source_type="url",
                filename="",
                score="",
                score_details={},
                cite_index=self.record_ops + index,
                search_type=self.name,
                tool_sign=self.tool_sign
            )
            search_results_json.append(search_result_message.to_dict())
            search_results_return.append(search_result_message.to_model_dict())

        self.record_ops += len(search_results_return)

        # Record detailed content of this search
        if self.observer:
            search_results_data = json.dumps(
                search_results_json, ensure_ascii=False)
            self.observer.add_message(
                "", ProcessType.SEARCH_CONTENT, search_results_data)
        return json.dumps(search_results_return, ensure_ascii=False)

    def _search_serply(self, query: str) -> list:
        """
        Perform a search on the Serply API and return the organic results.
        :param query: Search query to perform.
        """
        params = {"q": query, "num": self.max_results}
        headers = {
            "X-Api-Key": self.serply_api_key,
            "Accept": "application/json",
            # Serply is fronted by Cloudflare, which rejects the default
            # httpx User-Agent with a 1010 error, so send an explicit one.
            "User-Agent": "nexent-serply-search-tool",
        }

        try:
            response = httpx.get(
                SERPLY_SEARCH_ENDPOINT, params=params, headers=headers, timeout=30.0)
            response.raise_for_status()
            result = response.json()
        except httpx.RequestError as e:
            raise Exception(f"Serply API request failed: {str(e)}")
        except httpx.HTTPStatusError as e:
            raise Exception(f"Serply API HTTP error: {str(e)}")
        except json.JSONDecodeError as e:
            raise Exception(f"Failed to parse Serply API response: {str(e)}")

        results = result.get("results") or []
        if not isinstance(results, list):
            return []
        return results

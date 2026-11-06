# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import json
import logging

import httpx
from pydantic import Field
from smolagents.tools import Tool

from ..utils.observer import MessageObserver, ProcessType
from ..utils.pydantic_utils import unwrap_field_info
from ..utils.tools_common_message import SearchResultTextMessage, ToolCategory, ToolSign


# Get logger instance
logger = logging.getLogger("outcrawl_search_tool")


class OutcrawlSearchTool(Tool):
    name = "outcrawl_search"
    description = "Performs an internet search based on your query using Outcrawl, then returns the top search results. " \
                  "A tool for retrieving publicly available information, news, general knowledge, or non-proprietary data " \
                  "from the internet. When page content is enabled, each result carries the page text as markdown."

    description_zh = "基于你的查询词使用 Outcrawl 进行互联网搜索，返回最相关的搜索结果。适用于获取公开信息、新闻、通用知识或互联网上的非专有数据。" \
                     "开启网页正文后，每条结果附带 Markdown 格式的网页正文。"

    inputs = {
        "query": {
            "type": "string",
            "description": "The search query to perform.",
            "description_zh": "要执行的搜索查询词"
        }
    }

    init_param_descriptions = {
        "outcrawl_api_key": {
            "description": "Outcrawl API key",
            "description_zh": "Outcrawl API 密钥"
        },
        "max_results": {
            "description": "Maximum number of search results",
            "description_zh": "返回搜索结果的最大数量"
        },
        "scrape_content": {
            "description": "Whether to return the page content as markdown instead of the search snippet",
            "description_zh": "是否返回 Markdown 格式的网页正文以替代搜索摘要"
        }
    }
    output_type = "string"
    category = ToolCategory.SEARCH.value
    tool_sign = ToolSign.OUTCRAWL_SEARCH.value  # Used to distinguish different index sources in summary
    endpoint = "https://api.outcrawl.ai/v1/search"
    timeout_seconds = 60

    def __init__(self, outcrawl_api_key: str = Field(description="Outcrawl API key"),
                 observer: MessageObserver = Field(description="Message observer", default=None, exclude=True),
                 max_results: int = Field(description="Maximum number of search results", default=5, ge=1, le=20),
                 scrape_content: bool = Field(
                     description="Whether to return the page content as markdown instead of the search snippet",
                     default=False)
                 ):

        super().__init__()

        api_key = unwrap_field_info(outcrawl_api_key)
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("Outcrawl API key is required.")
        max_results = unwrap_field_info(max_results)
        if type(max_results) is not int or not 1 <= max_results <= 20:
            raise ValueError("max_results must be an integer between 1 and 20.")
        scrape_content = unwrap_field_info(scrape_content)
        if type(scrape_content) is not bool:
            raise ValueError("scrape_content must be a boolean.")

        self._api_key = api_key.strip()
        self.observer = unwrap_field_info(observer)
        self.max_results = max_results
        self.scrape_content = scrape_content
        self.record_ops = 1  # Used to record sequence number

    def _search(self, query: str) -> list:
        payload = {"query": query, "limit": self.max_results}
        if self.scrape_content:
            payload.update(scrape=True, formats=["markdown"])
        try:
            response = httpx.post(
                self.endpoint, json=payload, timeout=self.timeout_seconds,
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Outcrawl search request failed: {type(exc).__name__}") from None
        if response.status_code != 200:
            try:
                detail = response.json().get("message")
            except (ValueError, AttributeError):
                detail = None
            message = f"Outcrawl search failed (HTTP {response.status_code})"
            raise RuntimeError(f"{message}: {detail}" if isinstance(detail, str) and detail else message)
        try:
            data = response.json()
        except ValueError:
            raise RuntimeError("Invalid Outcrawl search response JSON.") from None
        if not isinstance(data, dict) or not isinstance(data.get("hits"), list):
            raise RuntimeError("Invalid Outcrawl search response structure.")
        logger.info("outcrawl_search hits=%s credits=%s", len(data["hits"]), (data.get("usage") or {}).get("credits"))
        return data["hits"]

    def forward(self, query: str) -> str:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must contain search terms.")
        query = query.strip()

        # Send tool running message
        if self.observer:
            card_content = [{"icon": "search", "text": query}]
            self.observer.add_message("", ProcessType.CARD, json.dumps(
                card_content, ensure_ascii=False))

        hits = [hit for hit in self._search(query) if isinstance(hit, dict) and hit.get("url")]
        if len(hits) == 0:
            raise Exception(
                'No results found! Try a less restrictive/shorter query.')

        search_results_json = []  # Format search results into a unified structure
        search_results_return = []  # Format for input to the large model
        for index, hit in enumerate(hits[:self.max_results]):
            text = hit.get("markdown") if self.scrape_content else None
            search_result_message = SearchResultTextMessage(
                title=hit.get("title") or hit["url"],
                url=hit["url"],
                text=text if isinstance(text, str) and text.strip() else hit.get("snippet", ""),
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

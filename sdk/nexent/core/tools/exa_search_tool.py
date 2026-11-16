# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import json
import logging

from exa_py import Exa
from pydantic import Field
from smolagents.tools import Tool

from ..utils.observer import MessageObserver, ProcessType
from ..utils.pydantic_utils import unwrap_field_info
from ..utils.search_images import publish_filtered_images
from ..utils.tools_common_message import SearchResultTextMessage, ToolCategory, ToolSign


# Get logger instance
logger = logging.getLogger("exa_search_tool")


class ExaSearchTool(Tool):
    name = "exa_search"
    description = "Performs a internet search based on your query (think a Google search) then returns the top search results. " \
                  "A tool for retrieving publicly available information, news, general knowledge, or non-proprietary data from the internet. " \
                  "Use this for real-time open-domain updates, broad topics, or or general knowledge queries"

    description_zh = "基于你的查询词进行互联网搜索，返回最相关的搜索结果。适用于获取公开信息、新闻、通用知识或互联网上的非专有数据。特别适合实时信息更新、广泛话题或通用知识查询。"

    inputs = {
        "query": {
            "type": "string",
            "description": "The search query to perform.",
            "description_zh": "要执行的搜索查询词"
        }
    }

    init_param_descriptions = {
        "exa_api_key": {
            "description": "Exa API key",
            "description_zh": "Exa API 密钥"
        },
        "max_results": {
            "description": "Maximum number of search results",
            "description_zh": "返回搜索结果的最大数量"
        },
        "image_filter": {
            "description": "Whether to enable image filtering",
            "description_zh": "是否启用图片过滤"
        }
    }

    output_type = "string"
    category = ToolCategory.SEARCH.value
    tool_sign = ToolSign.EXA_SEARCH.value  # Used to distinguish different index sources in summary

    def __init__(self, exa_api_key:str=Field(description="EXA API key"),
                 observer: MessageObserver=Field(description="Message observer", default=None, exclude=True),
                 max_results:int=Field(description="Maximum number of search results", default=3, ge=1, le=100),
                 image_filter: bool = Field(description="Whether to enable image filtering", default=True)
     ):

        super().__init__()

        self.observer = observer
        self.exa = Exa(api_key=exa_api_key)
        self.max_results = max(1, min(int(unwrap_field_info(max_results) or 3), 100))
        self.image_filter = image_filter
        self.record_ops = 1  # Used to record sequence number

        self.image_filterer = None

    def forward(self, query: str) -> str:
        # Perform exa search
        exa_search_result = self.exa.search_and_contents(
            query,
            text={"max_characters": 2000},
            livecrawl="always",
            extras={"links": 0, "image_links": 10},
            num_results=self.max_results
        )
        if len(exa_search_result.results) == 0:
            raise Exception(
                'No results found! Try a less restrictive/shorter query.')

        # Tool running chunk is emitted by the SDK tool-call bridge in
        # core_agent.py so it is consistent across direct and code_action
        # invocations. We only emit the search card from inside the tool.
        if self.observer:
            card_content = [{"icon": "search", "text": query}]
            self.observer.add_message("", ProcessType.CARD, json.dumps(
                card_content, ensure_ascii=False))

        images_list_url = []
        search_results_json = []  # Format search results into a unified structure
        search_results_return = []  # Format for input to the large model
        for index, single_result in enumerate(exa_search_result.results):
            search_result_message = SearchResultTextMessage(
                title=single_result.title,
                url=single_result.url,
                text=single_result.text,
                published_date=single_result.published_date,
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
            images_list_url.extend(single_result.extras["image_links"])

        self.record_ops += len(search_results_return)

        # Deduplicate and filter image list
        images_list_url = list(dict.fromkeys(images_list_url))
        if len(images_list_url) > 0:
            if self.image_filter:
                self._filter_images(images_list_url, query)
            else:
                if self.observer:
                    search_images_list_json = json.dumps(
                        {"images_url": images_list_url}, ensure_ascii=False)
                    self.observer.add_message(
                        "", ProcessType.PICTURE_WEB, search_images_list_json)

        # Record detailed content of this search
        if self.observer:
            search_results_data = json.dumps(
                search_results_json, ensure_ascii=False)
            self.observer.add_message(
                "", ProcessType.SEARCH_CONTENT, search_results_data)
        return json.dumps(search_results_return, ensure_ascii=False)

    def _filter_images(self, images_list_url, query):
        publish_filtered_images(self.observer, self.image_filterer, images_list_url, query)

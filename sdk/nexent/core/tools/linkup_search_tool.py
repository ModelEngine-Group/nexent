import json
import logging
import os

from linkup import LinkupClient, LinkupSearchImageResult, LinkupSearchTextResult
from smolagents.tools import Tool
from pydantic import Field

from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import SearchResultTextMessage, ToolSign, ToolCategory

logger = logging.getLogger("linkup_search_tool")

class LinkupSearchTool(Tool):
    name = "linkup_search"
    description = (
        "Performs a search using the Linkup API and returns the top search results. "
        "A tool for retrieving publicly available information, news, general knowledge, or non-proprietary data from the internet. "
        "Use this for real-time open-domain updates, broad topics, or general knowledge queries."
    )
    inputs = {"query": {"type": "string", "description": "The search query to perform."}}
    output_type = "string"
    category = ToolCategory.SEARCH.value
    tool_sign = ToolSign.LINKUP_SEARCH.value  # Used to distinguish different index sources in summary

    def __init__(
        self,
        linkup_api_key: str = Field(description="Linkup API key"),
        observer: MessageObserver = Field(description="Message observer", default=None, exclude=True),
        max_results: int = Field(description="Maximum number of search results", default=3),
        image_filter: bool = Field(description="Whether to enable image filtering", default=True)
    ):
        super().__init__()
        self.observer = observer
        self.client = LinkupClient(api_key=linkup_api_key)
        self.max_results = max_results
        self.record_ops = 1
        self.running_prompt_en = "Searching the web..."
        self.running_prompt_zh = "网络搜索中..."
        self.image_filter = image_filter
        self.data_process_service = os.getenv("DATA_PROCESS_SERVICE")

    def forward(self, query: str) -> str:
        # Perform linkup search
        response = self.client.search(
            query=query,
            depth="standard",
            output_type="searchResults",
            include_images=True,
        )
        results = response.results[:self.max_results]
        if len(results) == 0:
            raise Exception('No results found! Try a less restrictive/shorter query.')

        # Send tool running message
        if self.observer:
            running_prompt = self.running_prompt_zh if self.observer.lang == "zh" else self.running_prompt_en
            self.observer.add_message("", ProcessType.TOOL, running_prompt)
            card_content = [{"icon": "search", "text": query}]
            self.observer.add_message("", ProcessType.CARD, json.dumps(card_content, ensure_ascii=False))

        search_results_json = []
        search_results_return = []
        images_list_url = []
        for index, result in enumerate(results):
            if isinstance(result, LinkupSearchTextResult):
                search_result_message = SearchResultTextMessage(
                    title=result.name or "",
                    url=result.url or "",
                    text=result.content or "",
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
            elif isinstance(result, LinkupSearchImageResult):
                search_result_message = SearchResultTextMessage(
                    title=result.name or "",
                    url="",
                    text="This is a pure image result",
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
                images_list_url.append(result.url)

        self.record_ops += len(search_results_return)

        # Deduplicate image list
        images_list_url = list(dict.fromkeys(images_list_url))
        if len(images_list_url) > 0:
            if self.image_filter:
                self._filter_images(images_list_url, query)
            else:
                if self.observer:
                    search_images_list_json = json.dumps({"images_url": images_list_url}, ensure_ascii=False)
                    self.observer.add_message("", ProcessType.PICTURE_WEB, search_images_list_json)

        # Record detailed content of this search
        if self.observer:
            search_results_data = json.dumps(search_results_json, ensure_ascii=False)
            self.observer.add_message("", ProcessType.SEARCH_CONTENT, search_results_data)
        return json.dumps(search_results_return, ensure_ascii=False)

    def _filter_images(self, images_list_url, query):
        """
        Execute image filtering operation directly using the data processing service
        :param images_list_url: List of image URLs to filter
        :param query: Search query, used to filter images related to the query
        """
        import asyncio
        import aiohttp
        try:
            # Define positive and negative prompts
            positive_prompt = query
            negative_prompt = "logo or banner or background or advertisement or icon or avatar"

            # Define the async function to perform the filtering
            async def process_images():
                # Maximum number of concurrent requests
                semaphore = asyncio.Semaphore(10)  # Limit concurrent requests

                # Create a ClientSession
                connector = aiohttp.TCPConnector(limit=0)
                timeout = aiohttp.ClientTimeout(total=2)

                async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                    # Create a function to process a single image
                    async def process_single_image(img_url):
                        async with semaphore:
                            try:
                                api_url = f"{self.data_process_service}/tasks/filter_important_image"
                                data = {
                                    'image_url': img_url,
                                    'positive_prompt': positive_prompt,
                                    'negative_prompt': negative_prompt
                                }
                                async with session.post(api_url, data=data) as response:
                                    if response.status != 200:
                                        logger.info(f"API error for {img_url}: {response.status}")
                                        return None
                                    result = await response.json()
                                    if result.get("is_important", False):
                                        logger.info(f"Important image: {img_url}")
                                        return img_url
                                    return None
                            except Exception as e:
                                logger.info(f"Error processing image {img_url}: {str(e)}")
                                return None
                    tasks = [process_single_image(url) for url in images_list_url]
                    results = await asyncio.gather(*tasks)
                    filtered_images = [url for url in results if url is not None]
                    if self.observer:
                        filtered_images_json = json.dumps({"images_url": filtered_images}, ensure_ascii=False)
                        self.observer.add_message("", ProcessType.PICTURE_WEB, filtered_images_json)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(process_images())
            finally:
                loop.close()
        except Exception as e:
            logger.info(f"Image filtering error: {str(e)}")
            if self.observer:
                filtered_images_json = json.dumps({"images_url": images_list_url}, ensure_ascii=False)
                self.observer.add_message("", ProcessType.PICTURE_WEB, filtered_images_json)

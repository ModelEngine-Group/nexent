import asyncio
import json
import logging
import os
import aiohttp
from tavily import TavilyClient
from smolagents.tools import Tool
from pydantic import Field

from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import SearchResultTextMessage, ToolSign, ToolCategory

# Get logger instance
logger = logging.getLogger("tavily_search_tool")


class TavilySearchTool(Tool):
    name = "tavily_search"
    description = "Performs a internet search based on your query (think a Google search) then returns the top search results. " \
                  "A tool for retrieving publicly available information, news, general knowledge, or non-proprietary data from the internet. " \
                  "Use this for real-time open-domain updates, broad topics, or or general knowledge queries" \

    inputs = {"query": {"type": "string", "description": "The search query to perform."}}
    output_type = "string"
    category = ToolCategory.SEARCH.value
    tool_sign = ToolSign.TAVILY_SEARCH.value  # Used to distinguish different index sources in summary

    def __init__(self, tavily_api_key:str=Field(description="Tavily API key"),
                 observer: MessageObserver=Field(description="Message observer", default=None, exclude=True),
                 max_results:int=Field(description="Maximum number of search results", default=3),
                 image_filter: bool = Field(description="Whether to enable image filtering", default=True)
     ):

        super().__init__()

        self.observer = observer
        self.tavily = TavilyClient(api_key=tavily_api_key)
        self.max_results = max_results
        self.image_filter = image_filter
        self.record_ops = 0  # Used to record sequence number
        self.running_prompt_en = "Searching the web..."
        self.running_prompt_zh = "网络搜索中..."
        
        # TODO add data_process_service
        self.data_process_service = os.getenv("DATA_PROCESS_SERVICE")

    def forward(self, query: str) -> str:
        # Perform tavily search
        tavily_search_result = self.tavily.search(
            query=query,
            max_results=self.max_results,
            include_images=True,
        )
        images_list_url = tavily_search_result.get("images", [])
        tavily_search_result = tavily_search_result.get("results", [])
        if len(tavily_search_result) == 0:
            raise Exception(
                'No results found! Try a less restrictive/shorter query.')

        # Send tool running message
        if self.observer:
            running_prompt = self.running_prompt_zh if self.observer.lang=="zh" else self.running_prompt_en
            self.observer.add_message("", ProcessType.TOOL, running_prompt)
            card_content = [{"icon": "search", "text": query}]
            self.observer.add_message("", ProcessType.CARD, json.dumps(
                card_content, ensure_ascii=False))

        search_results_json = []  # Format search results into a unified structure
        search_results_return = []  # Format for input to the large model
        for index, single_result in enumerate(tavily_search_result):
            search_result_message = SearchResultTextMessage(
                title=single_result.get("title", ""),
                url=single_result.get("url", ""),
                text=single_result.get("content", ""),
                published_date=single_result.get("published_date", ""),
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
        """
        Execute image filtering operation directly using the data processing service
        :param images_list_url: List of image URLs to filter
        :param query: Search query, used to filter images related to the query
        """
        try:
            # Define positive and negative prompts
            positive_prompt = query
            negative_prompt = "logo or banner or background or advertisement or icon or avatar"

            # Define the async function to perform the filtering
            async def process_images():
                # Maximum number of concurrent requests
                semaphore = asyncio.Semaphore(10)  # Limit concurrent requests

                # Create a ClientSession
                connector = aiohttp.TCPConnector(
                    limit=0)  # No limit on connections
                timeout = aiohttp.ClientTimeout(total=2)  # 2 seconds timeout

                async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                    # Create a function to process a single image
                    async def process_single_image(img_url):
                        async with semaphore:  # Limit concurrency
                            try:
                                # Create API endpoint URL
                                api_url = f"{self.data_process_service}/tasks/filter_important_image"

                                # Prepare form data
                                data = {
                                    'image_url': img_url,
                                    'positive_prompt': positive_prompt,
                                    'negative_prompt': negative_prompt
                                }

                                # Make async API request
                                async with session.post(api_url, data=data) as response:
                                    if response.status != 200:
                                        logger.info(
                                            f"API error for {img_url}: {response.status}")
                                        return None

                                    result = await response.json()
                                    if result.get("is_important", False):
                                        logger.info(f"Important image: {img_url}")
                                        return img_url
                                    return None
                            except Exception as e:
                                logger.info(
                                    f"Error processing image {img_url}: {str(e)}")
                                return None

                    # Process all images concurrently
                    tasks = [process_single_image(url) for url in images_list_url]
                    results = await asyncio.gather(*tasks)

                    # Filter out None results
                    filtered_images = [
                        url for url in results if url is not None]

                    # Notify results through observer after filtering
                    if self.observer:
                        # Send the filtered images list
                        filtered_images_json = json.dumps(
                            {"images_url": filtered_images}, ensure_ascii=False)
                        self.observer.add_message(
                            "", ProcessType.PICTURE_WEB, filtered_images_json)

            # Create a new event loop and run the async function in the current thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(process_images())
            finally:
                loop.close()

        except Exception as e:
            # Handle exceptions in filtering process, log the error
            logger.info(f"Image filtering error: {str(e)}")
            # Send unfiltered image_url in case of error
            if self.observer:
                filtered_images_json = json.dumps(
                    {"images_url": images_list_url}, ensure_ascii=False)
                self.observer.add_message(
                    "", ProcessType.PICTURE_WEB, filtered_images_json)

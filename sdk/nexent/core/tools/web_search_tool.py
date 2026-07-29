"""Zero-config web search tool.

Scrapes search-engine result pages directly (Baidu / Bing / DuckDuckGo) — no
API key required. Output is the same ``SearchResultTextMessage`` shape as
``TavilySearchTool`` so agents can swap it in transparently.

Design ref: nexent-web-search-tool-design-2026-07-29.md
"""

import json
import logging
import time
from typing import Dict, List, Optional
from urllib.parse import parse_qs, quote_plus, urlparse

import requests
from bs4 import BeautifulSoup
from pydantic import Field
from smolagents.tools import Tool

from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import SearchResultTextMessage, ToolCategory, ToolSign

logger = logging.getLogger("web_search_tool")


# Search-engine URL templates (query is URL-encoded before formatting).
URLS: Dict[str, str] = {
    "baidu": "https://www.baidu.com/s?wd={query}",
    "bing": "https://cn.bing.com/search?q={query}",
    "duckduckgo": "https://html.duckduckgo.com/html/?q={query}",
}


class _WebSearchResult:
    """Unified result structure for all engines."""

    __slots__ = ("title", "url", "snippet")

    def __init__(self, title: str, url: str, snippet: str):
        self.title = title
        self.url = url
        self.snippet = snippet


def _parse_baidu(html: str) -> List[_WebSearchResult]:
    """Parse a Baidu search results page."""
    soup = BeautifulSoup(html, "html.parser")
    results: List[_WebSearchResult] = []
    for item in soup.select("div.result, div.c-container"):
        # Skip Baidu ads (they carry tuiguang / ec_tuiguang markers).
        item_id = item.get("id", "") or ""
        tpl = item.get("tpl", "") or ""
        cmatchid = item.get("cmatchid", "") or ""
        if any(k in (item_id + tpl + cmatchid + " ".join(item.get("class", [])))
               for k in ("tuiguang", "ec_tuiguang", "ec-ad", "ec_ppzq")):
            continue
        title_tag = item.select_one("h3 a")
        if not title_tag:
            continue
        title = title_tag.get_text(strip=True)
        url = title_tag.get("href", "")
        # Baidu puts the snippet in various containers — try several.
        snippet = ""
        for sel in (
            "div.c-abstract",
            "span.content-right_8Zs40",
            "div.c-span-last",
            "div.c-row",
            "[class*='content-right']",
            "[class*='abstract']",
        ):
            snippet_tag = item.select_one(sel)
            if snippet_tag:
                snippet = snippet_tag.get_text(strip=True)
                if snippet:
                    break
        # Fallback: grab the longest text block under the item.
        if not snippet:
            texts = [t.get_text(strip=True) for t in item.find_all(string=False)]
            texts = [t for t in texts if len(t) > 20 and t != title]
            snippet = max(texts, key=len) if texts else ""
        if title and url:
            results.append(_WebSearchResult(title=title, url=url, snippet=snippet))
    return results


def _parse_bing(html: str) -> List[_WebSearchResult]:
    """Parse a Bing search results page."""
    soup = BeautifulSoup(html, "html.parser")
    results: List[_WebSearchResult] = []
    for item in soup.select("li.b_algo"):
        title_tag = item.select_one("h2 a")
        if not title_tag:
            continue
        title = title_tag.get_text(strip=True)
        url = title_tag.get("href", "")
        # Bing snippet: try multiple selectors.
        snippet = ""
        for sel in (
            "div.b_caption p",
            ".b_caption p",
            "p",
            "div.b_caption",
        ):
            snippet_tag = item.select_one(sel)
            if snippet_tag:
                t = snippet_tag.get_text(strip=True)
                if t:
                    snippet = t
                    break
        if title and url:
            results.append(_WebSearchResult(title=title, url=url, snippet=snippet))
    return results


def _parse_duckduckgo(html: str) -> List[_WebSearchResult]:
    """Parse a DuckDuckGo HTML results page."""
    soup = BeautifulSoup(html, "html.parser")
    results: List[_WebSearchResult] = []
    for item in soup.select("div.result, div.web-result"):
        title_tag = item.select_one("h2 a, a.result__a")
        if not title_tag:
            continue
        title = title_tag.get_text(strip=True)
        url = title_tag.get("href", "")
        # DuckDuckGo wraps URLs in a redirect; extract the real URL.
        if "duckduckgo.com/l/?uddg=" in url:
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            url = params.get("uddg", [url])[0]
        snippet_tag = item.select_one("a.result__snippet, div.snippet, .result__snippet")
        snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
        if title and url:
            results.append(_WebSearchResult(title=title, url=url, snippet=snippet))
    return results


PARSERS = {
    "baidu": _parse_baidu,
    "bing": _parse_bing,
    "duckduckgo": _parse_duckduckgo,
}


class WebSearchTool(Tool):
    """Zero-config web search via direct search-engine scraping.

    No API key. Multi-engine with auto language detection (CJK -> Baidu,
    else Bing). Output matches ``TavilySearchTool`` (``SearchResultTextMessage``).
    """

    name = "web_search"
    description = (
        "Performs an internet search based on your query. "
        "A zero-config tool that scrapes search engine result pages directly. "
        "Use this for real-time information, news, or general knowledge queries. "
        "No API key required."
    )
    description_zh = (
        "基于查询词进行互联网搜索，直接抓取搜索引擎结果页面。"
        "适用于获取实时信息、新闻或通用知识。无需 API Key 配置。"
    )

    inputs = {
        "query": {
            "type": "string",
            "description": "The search query to perform.",
            "description_zh": "要执行的搜索查询词",
        }
    }

    init_param_descriptions = {
        "max_results": {
            "description": "Maximum number of search results",
            "description_zh": "返回搜索结果的最大数量",
        },
        "engine": {
            "description": "Search engine: auto/bing/baidu/duckduckgo",
            "description_zh": "搜索引擎：auto/bing/baidu/duckduckgo",
        },
    }

    output_type = "string"
    category = ToolCategory.SEARCH.value
    tool_sign = ToolSign.WEB_SEARCH.value

    def __init__(
        self,
        observer: MessageObserver = Field(
            description="Message observer", default=None, exclude=True
        ),
        max_results: int = Field(
            description="Maximum number of search results", default=10
        ),
        engine: str = Field(
            description="Search engine: auto/bing/baidu/duckduckgo", default="auto"
        ),
    ):
        """Initialize WebSearchTool.

        No API key required. Uses HTTP GET to scrape search engine result pages.

        Args:
            observer: Message observer instance. Defaults to None.
            max_results: Maximum number of search results. Defaults to 10.
            engine: Search engine strategy. ``"auto"`` detects query language
                and picks the best engine (Chinese -> Baidu, English -> Bing).
        """
        super().__init__()
        # Coerce FieldInfo defaults to real values (smolagents passes FieldInfo
        # objects when a param isn't explicitly provided via tool-instance params).
        self.observer = observer if isinstance(observer, MessageObserver) else None
        self.max_results = max_results if isinstance(max_results, int) else 10
        self.engine = engine if isinstance(engine, str) else "auto"
        self.record_ops = 1  # Sequence counter, same pattern as TavilySearchTool

        # Browser-like headers to reduce the chance of being blocked as a bot.
        self._headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

    def _select_engine(self, query: str) -> str:
        """Auto-select search engine based on query language."""
        if self.engine != "auto":
            return self.engine
        # Default to Bing: cn.bing.com handles both Chinese and English well,
        # returns real article URLs (not redirect links) and rich snippets.
        # Baidu is available via explicit engine="baidu" but its snippet
        # extraction is less reliable due to frequent HTML structure changes.
        return "bing"

    def _fetch_with_retry(self, url: str, engine: str) -> Optional[str]:
        """Fetch a URL with a single retry that first warms cookies."""
        session = requests.Session()
        session.headers.update(self._headers)

        for attempt in range(2):
            try:
                response = session.get(url, timeout=10, allow_redirects=True)
                if response.status_code == 200:
                    return response.text
                if response.status_code in (403, 429) and attempt == 0:
                    # Rate limited: visit the engine homepage for cookies, then retry.
                    homepage = URLS[engine].split("/s?")[0].split("/search?")[0]
                    if "duckduckgo" in engine:
                        homepage = "https://html.duckduckgo.com/"
                    try:
                        session.get(homepage, timeout=5)
                    except requests.RequestException:
                        pass
                    time.sleep(1.5)
                    continue
            except requests.RequestException:
                if attempt == 0:
                    time.sleep(2)
                    continue
        return None

    def forward(self, query: str) -> str:
        """Perform a web search and return results as JSON.

        Args:
            query: Search query string.

        Returns:
            JSON string of search results in ``SearchResultTextMessage`` format.

        Raises:
            Exception: If all engines fail or no results are found.
        """
        engine = self._select_engine(query)
        search_url = URLS[engine].format(query=quote_plus(query))

        html = self._fetch_with_retry(search_url, engine)
        if not html:
            # Fallback to another engine.
            fallback_engine = "duckduckgo" if engine != "duckduckgo" else "bing"
            search_url = URLS[fallback_engine].format(query=quote_plus(query))
            html = self._fetch_with_retry(search_url, fallback_engine)
            engine = fallback_engine

        if not html:
            raise Exception(f"All search engines failed for query: {query}")

        parser = PARSERS.get(engine)
        if parser is None:
            raise Exception(f"Unsupported search engine: {engine}")
        raw_results = parser(html)

        if not raw_results:
            raise Exception(f"No results found for query: {query}")

        raw_results = raw_results[: self.max_results]

        # Send a search card (same pattern as TavilySearchTool).
        if self.observer is not None and hasattr(self.observer, "add_message"):
            card_content = [{"icon": "search", "text": query}]
            self.observer.add_message(
                "", ProcessType.CARD, json.dumps(card_content, ensure_ascii=False)
            )

        # Convert to the unified SearchResultTextMessage format.
        search_results_json = []
        search_results_return = []
        for index, result in enumerate(raw_results):
            result_message = SearchResultTextMessage(
                title=result.title,
                url=result.url,
                text=result.snippet,
                published_date="",  # Web search has no reliable dates.
                source_type="url",
                filename="",
                score="",
                score_details={},
                cite_index=self.record_ops + index,
                search_type=self.name,
                tool_sign=self.tool_sign,
            )
            search_results_json.append(result_message.to_dict())
            search_results_return.append(result_message.to_model_dict())

        self.record_ops += len(search_results_return)

        # Record detailed content via observer.
        if self.observer is not None and hasattr(self.observer, "add_message"):
            search_results_data = json.dumps(search_results_json, ensure_ascii=False)
            self.observer.add_message(
                "", ProcessType.SEARCH_CONTENT, search_results_data
            )

        return json.dumps(search_results_return, ensure_ascii=False)

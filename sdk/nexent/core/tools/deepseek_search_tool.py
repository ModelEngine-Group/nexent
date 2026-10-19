# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""DeepSeek Search adapter with platform source references and bounded retries."""

import json
import logging
import math
import random
import re
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx
from pydantic import Field
from smolagents.tools import Tool

from ..utils.observer import MessageObserver, ProcessType
from ..utils.pydantic_utils import unwrap_field_info
from ..utils.tools_common_message import SearchResultTextMessage, ToolCategory, ToolSign


logger = logging.getLogger(__name__)
_QUERY_TOKEN = re.compile(r'''(?:[^\s"']|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')+''')


class DeepSeekSearchTool(Tool):
    name = "deepseek_search"
    description = "Search public webpages using DeepSeek for current information and return citable sources."
    description_zh = "使用 DeepSeek 检索公开网页，获取实时信息并返回可引用的来源。"
    inputs = {
        "query": {
            "type": "string",
            "description": (
                'Search query. Supports site:domain (multiple sites joined by OR), -site:domain, '
                '-keyword, -"excluded phrase", "exact phrase", after:YYYY-MM-DD and before:YYYY-MM-DD '
                '(years also accepted). The current UI language replaces unquoted lang: operators with '
                'one trailing lang:zh or lang:en. Keep the query within 120 Unicode characters; the final '
                'query including the language suffix must not exceed 128. '
                'Example: DeepSeek site:github.com after:2025.'
            ),
            "description_zh": (
                '搜索查询词，支持 site: 限定站点（多个站点用 OR 连接）、-site: 排除站点、'
                '-关键词及 -"短语" 排除内容、"精确短语" 精确匹配、after: 和 before: 限定日期或年份。'
                '系统按当前页面语言将引号外 lang: 操作符统一替换为末尾的 lang:zh 或 lang:en。'
                '通常请将输入控制在 120 个 Unicode 字符以内，追加后总长度不得超过 128。'
                '示例 DeepSeek site:github.com after:2025。'
            ),
        }
    }
    output_type = "string"
    category = ToolCategory.SEARCH.value
    tool_sign = ToolSign.DEEPSEEK_SEARCH.value
    labels = ["search"]
    endpoint = "https://api.deepseek.com/v1/tools/search"
    init_param_descriptions = {
        "deepseek_api_key": {"description_zh": "DeepSeek API 密钥"},
        "max_results": {"description_zh": "请求结果数量，质量过滤后可能少于此数"},
        "only_high_quality": {"description_zh": "开启后仅返回排序分不低于 1.5 的结果"},
        "need_content": {"description_zh": "返回网页正文，缺失时使用摘要"},
        "timeout_seconds": {"description_zh": "每次 HTTP 尝试的网络超时秒数"},
        "max_retries": {"description_zh": "失败后的最大重试次数"},
    }

    def __init__(
        self,
        deepseek_api_key: str = Field(description="DeepSeek API key", min_length=1),
        max_results: int = Field(default=10, ge=1, le=50, description="Requested result count before quality filtering"),
        only_high_quality: bool = Field(
            default=False, description="When enabled, return only results with rerank score >= 1.5; may return fewer results"
        ),
        need_content: bool = Field(default=False, description="Return webpage content, falling back to summaries"),
        timeout_seconds: int = Field(default=30, ge=1, le=120, description="Network timeout seconds per attempt"),
        max_retries: int = Field(default=2, ge=0, le=2, description="Maximum additional HTTP attempts"),
        observer: MessageObserver = Field(default=None, exclude=True, description="Message observer"),
        language: str = Field(default="zh", exclude=True, description="Run-scoped frontend language"),
    ):
        super().__init__()
        key = unwrap_field_info(deepseek_api_key)
        if not isinstance(key, str) or not key.strip():
            raise ValueError("DeepSeek API key is required.")
        self._api_key = key.strip()
        for name, value, lower, upper in (
            ("max_results", max_results, 1, 50),
            ("timeout_seconds", timeout_seconds, 1, 120), ("max_retries", max_retries, 0, 2),
        ):
            value = unwrap_field_info(value)
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError(f"{name} must be an integer between {lower} and {upper}.")
            setattr(self, name, value)
        for name, value in (("only_high_quality", only_high_quality), ("need_content", need_content)):
            value = unwrap_field_info(value)
            if type(value) is not bool:
                raise ValueError(f"{name} must be a boolean.")
            setattr(self, name, value)
        language = unwrap_field_info(language)
        self.language = language.lower().replace("_", "-").split("-")[0] if isinstance(language, str) else ""
        if self.language not in ("zh", "en"):
            raise ValueError("language must be zh or en.")
        self.observer = unwrap_field_info(observer)
        self.record_ops = 1
        self._index_lock = threading.Lock()

    def _prepare_query(self, query: str) -> str:
        if not isinstance(query, str):
            raise ValueError("query must be a string.")
        query = _QUERY_TOKEN.sub(
            lambda match: "" if re.fullmatch(r"lang:[a-zA-Z,-]+", match.group()) else match.group(), query
        ).strip()
        if not query:
            raise ValueError("query must contain search terms.")
        final = f"{query} lang:{self.language}"
        if len(final) > 128:
            raise ValueError("query including the language suffix must not exceed 128 Unicode characters; shorten it.")
        return final

    def _retry_delay(self, attempt: int, response: httpx.Response | None) -> float | None:
        retry_after = response.headers.get("Retry-After") if response is not None else None
        if retry_after:
            try:
                delay = float(retry_after)
            except ValueError:
                try:
                    delay = (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    delay = -1
            if math.isfinite(delay) and delay >= 0:
                return delay if delay <= 10 else None
        return 2 ** attempt + random.uniform(0, 0.5)

    def _request(self, query: str) -> dict:
        payload = {"query": query, "count": self.max_results, "need_content": self.need_content}
        messages = {
            400: "DeepSeek rejected the search parameters.", 401: "DeepSeek API key is invalid.",
            402: "DeepSeek account balance is insufficient.", 413: "DeepSeek search request is too large.",
            429: "DeepSeek search is rate limited; try again later.",
        }
        with httpx.Client(timeout=self.timeout_seconds, follow_redirects=False) as client:
            for attempt in range(self.max_retries + 1):
                response = None
                started = time.monotonic()
                try:
                    response = client.post(
                        self.endpoint, json=payload,
                        headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                    )
                except httpx.TransportError:
                    failure = "DeepSeek search network failure or timeout; try again later."
                    retryable = True
                else:
                    status = response.status_code
                    logger.info("deepseek_search attempt=%s status=%s elapsed=%.3f",
                                attempt + 1, status, time.monotonic() - started)
                    if status == 200:
                        try:
                            data = response.json()
                        except ValueError:
                            raise RuntimeError("Invalid DeepSeek search response JSON.") from None
                        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                            raise RuntimeError("Invalid DeepSeek search response structure.")
                        return data
                    failure = messages.get(status, f"DeepSeek search failed (HTTP {status}); try again later.")
                    retryable = status in (408, 429) or status >= 500
                if not retryable or attempt == self.max_retries:
                    raise RuntimeError(failure) from None
                delay = self._retry_delay(attempt, response)
                if delay is None:
                    raise RuntimeError(failure) from None
                time.sleep(delay)
        raise RuntimeError("DeepSeek search failed.")

    def _map_results(self, results: list) -> list[dict]:
        messages = []
        seen = set()
        valid_count = 0
        for item in results:
            if not isinstance(item, dict):
                continue
            score = item.get("rerank_score")
            if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 3:
                continue
            url = item.get("url")
            try:
                parsed = urlsplit(url) if isinstance(url, str) else None
                valid_url = parsed and parsed.scheme in ("http", "https") and parsed.hostname
            except ValueError:
                valid_url = False
            if not valid_url:
                continue
            fields = ("content", "summary", "snippet") if self.need_content else ("summary", "snippet", "content")
            source = next((field for field in fields if isinstance(item.get(field), str) and item[field].strip()), None)
            if source is None:
                continue
            valid_count += 1
            if (self.only_high_quality and score < 1.5) or url in seen:
                continue
            seen.add(url)
            metadata = {key: item.get(key) for key in ("rerank_score", "authority", "snippet", "site_name", "site_icon")}
            metadata.update(text_source=source)
            messages.append({
                "title": item.get("title") or url, "url": url, "text": item[source],
                "published_date": item.get("date"), "source_type": "url", "filename": "", "score": "",
                "score_details": {"deepseek": metadata}, "search_type": self.name, "tool_sign": self.tool_sign,
            })
        if results and not valid_count:
            raise RuntimeError("Invalid DeepSeek search response results.")
        messages.sort(key=lambda item: item["score_details"]["deepseek"]["rerank_score"], reverse=True)
        return messages[:self.max_results]

    def forward(self, query: str) -> str:
        final_query = self._prepare_query(query)
        if self.observer:
            self.observer.add_message("", ProcessType.CARD, json.dumps(
                [{"icon": "search", "text": final_query}], ensure_ascii=False,
            ))
        messages = self._map_results(self._request(final_query)["results"])
        with self._index_lock:
            start = self.record_ops
            self.record_ops += len(messages)
        sources = [SearchResultTextMessage(**item, cite_index=start + i) for i, item in enumerate(messages)]
        if self.observer:
            self.observer.add_message("", ProcessType.SEARCH_CONTENT, json.dumps(
                [source.to_dict() for source in sources], ensure_ascii=False,
            ))
        return json.dumps([source.to_model_dict() for source in sources], ensure_ascii=False)

# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Exercise real SDK/HTTP/source serialization against a loopback provider."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock

import pytest
from nexent.core.agents.agent_model import ToolConfig
from nexent.core.agents.nexent_agent import NexentAgent
from nexent.core.tools import DeepSeekSearchTool
from nexent.core.utils.observer import MessageObserver, ProcessType


@pytest.mark.case_id("SEARCH-DEEPSEEK-D3-001")
@pytest.mark.stage("D3")
def test_deepseek_http_sources_and_language(monkeypatch):
    """SEARCH-DEEPSEEK-D3-001: real HTTP request, quality and source agreement."""
    captured = []

    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            captured.append((self.path, payload, self.headers.get("Authorization")))
            rows = [{"title": f"Result {i}", "url": f"https://example.com/{i}", "summary": f"Summary {i}",
                     "rerank_score": score, "authority": 3} for i, score in enumerate([1.49, 1.5, 3])]
            if payload["query"].startswith("filtered"):
                for row in rows:
                    row["rerank_score"] = 1
            body = json.dumps({"results": None if payload["query"].startswith("malformed") else rows}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    monkeypatch.setattr(DeepSeekSearchTool, "endpoint", f"http://127.0.0.1:{server.server_port}/v1/tools/search")
    try:
        for language in ("zh", "en"):
            observer = MessageObserver(lang=language)
            observer.add_message = Mock()
            factory = NexentAgent(observer=observer, model_config_list=[], stop_event=threading.Event())
            search = factory.create_local_tool(ToolConfig(
                class_name="DeepSeekSearchTool", name="deepseek_search", source="local",
                params={"deepseek_api_key": "synthetic", "only_high_quality": True, "language": language},
            ))
            results = json.loads(search.forward("topic site:example.com"))
            assert [item["title"] for item in results] == ["Result 1", "Result 2"]
            assert [item["reference_mark"] for item in results] == ["[[o1]]", "[[o2]]"]
            sources = json.loads(observer.add_message.call_args.args[2])
            assert observer.add_message.call_args.args[1] == ProcessType.SEARCH_CONTENT
            assert [f'o{item["cite_index"]}' for item in sources] == [item["index"] for item in results]
            assert sources[0]["url"] == "https://example.com/1"
            assert captured[-1] == ("/v1/tools/search", {
                "query": f"topic site:example.com lang:{language}", "count": 10, "need_content": False,
            }, "Bearer synthetic")
            assert "synthetic" not in json.dumps(results) + json.dumps(sources)
            search.only_high_quality = False
            assert len(json.loads(search.forward("topic"))) == 3
        assert len(captured) == 4
        search.only_high_quality = True
        next_index = search.record_ops
        assert search.forward("filtered") == "[]"
        assert json.loads(observer.add_message.call_args.args[2]) == []
        assert search.record_ops == next_index
        with pytest.raises(RuntimeError, match="response"):
            search.forward("malformed")
        assert len(captured) == 6
        assert search.record_ops == next_index
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
        assert not worker.is_alive()

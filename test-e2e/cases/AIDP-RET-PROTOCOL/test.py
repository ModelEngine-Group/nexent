# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Consumer HTTP contract: actual SDK wrappers, policy, transport and response conversion."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import httpx
import pytest

from nexent.core.ext_components.aidp.aidp_search_tool import AidpSearchError, AidpSearchTool
from nexent.core.ext_components.aidp.retrieval_config import SEARCH_METHODS, validate_config
from nexent.core.tools.ind_aidp_search_tool import IndependentAidpSearchError, IndependentAidpSearchTool
from nexent.core.utils.observer import MessageObserver

CASE_ID = "AIDP-RET-PROTOCOL"


@pytest.fixture
def provider():
    state = {"requests": [], "statuses": [], "body": {"result": [{"text_id":"chunk", "text":"fixture", "score":0,
             "pages":[2,"3"], "retrieval_source":{"methods":["graph_search"], "extra":"retained"}}]}}
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["requests"].append((self.path, self.headers.get("Authorization"), body))
            self.send_response(state["statuses"].pop(0) if state["statuses"] else 200)
            self.send_header("Content-Type","application/json")
            self.end_headers()
            self.wfile.write(state["body"] if isinstance(state["body"], bytes) else json.dumps(state["body"]).encode())

        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(("127.0.0.1",0),Handler)
    thread = Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def tools(url, **config):
    config = validate_config(config)
    return [cls(server_url=url, api_key="fixture-token", tenant_id="fixture",kds_list=["kb"], **config)
            for cls in (AidpSearchTool, IndependentAidpSearchTool)]


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage("D2")
@pytest.mark.parametrize("method",sorted(SEARCH_METHODS))
def test_wire_channels_and_sources(provider, method):
    url, state = provider
    policies = []
    for tool in tools(url, search_method=method, top_k=7, reranking_enable=False, multi_modal=False):
        tool.observer = MessageObserver()
        if isinstance(tool,AidpSearchTool):
            tool.set_allowed_kds(["kb"])
        with httpx.Client() as client:
            tool._http_client = client
            result = json.loads(tool.forward("fixture question"))
        path, auth, payload = state["requests"][-1]
        assert path == "/KnowledgeBase/Tenants/fixture/Retrieval/FusionSearch"
        assert auth == "Bearer fixture-token"
        assert payload["kds_list"] == ["kb"]
        assert payload["search_method"] == method
        assert payload["topk"] == 7 and payload["multi_modal_enable"] is False
        assert not {"top_k","multi_modal","reranking_mode","metadata_condition","file_reorder_enable"} & payload.keys()
        enabled = set(method.split("|"))
        assert ("graph_search_config" in payload) == ("graph_search" in enabled)
        assert ("hybrid_search_config" in payload) == bool(enabled & {"vector_search","full_text_search"})
        if "graph_search_config" in payload:
            assert payload["graph_search_config"] == {"graph_top_k":0,"graph_score_threshold":0,"graph_reranking_enable":False}
        if "hybrid_search_config" in payload:
            h=payload["hybrid_search_config"]
            assert h["hybrid_top_k"] == 0
            for channel,prefix in (("vector_search","vector"),("full_text_search","full_text")):
                assert (f"{prefix}_candidates" in h) == (channel in enabled)
                if channel in enabled:
                    assert h[f"{prefix}_candidates"]==7
                    assert h[f"{prefix}_score_threshold"]==0
        assert result["results"][0]["text"] == "fixture"
        messages = [json.loads(raw) for raw in tool.observer.get_cached_message()]
        chunk = json.loads(next(m["content"] for m in messages if m["type"] == "search_content"))[0]
        assert chunk["score"] == "0"
        assert chunk["score_details"]["chunk_id"] == "chunk"
        assert chunk["score_details"]["pages"] == [2,"3"]
        assert chunk["score_details"]["retrieval_source"] == state["body"]["result"][0]["retrieval_source"]
        policies.append(payload)
    assert policies[0] == policies[1]


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage("D2")
def test_wire_retry_errors_and_no_invalid_http(provider):
    url,state=provider
    for tool in tools(url):
        error=AidpSearchError if isinstance(tool,AidpSearchTool) else IndependentAidpSearchError
        for statuses,body,attempts,fails in [([503,200],{"result":[]},2,False),([503]*3,{"result":[]},3,True),([400],{"result":[]},1,True),([200],b"not-json",1,True),([200],{"result":{}},1,True)]:
            state.update(statuses=statuses,body=body)
            before=len(state["requests"])
            with httpx.Client() as client:
                tool._http_client=client
                if fails:
                    with pytest.raises((error,httpx.HTTPStatusError,ValueError)):
                        tool._execute_request("q",["kb"])
                else:
                    assert tool._execute_request("q",["kb"])==[]
            assert len(state["requests"])-before==attempts
    before=len(state["requests"])
    for config in ({"hybrid_top_k":8,"graph_top_k":5},{"reranking_enable":False,"graph_reranking_enable":True}):
        with pytest.raises(ValueError):
            tools(url,**config)
    assert len(state["requests"])==before

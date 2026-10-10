"""Regression coverage for the AIDP request captured during live integration."""
import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from test.ext_components.aidp.test_aidp_service import aidp_service_module
from test.ext_components.aidp.test_aidp_mgmt_mock_server import mock_aidp_server


def graph_config():
    return {
        "retrieve_subgraph_hop": "2", "no_think_mode": "是",
        "prompt_language": "中文", "domain": "常规", "prompt_text": "提取实体关系。",
        "synonym_merge_enable": "否", "disambiguation_enable": "否",
        "llm_model_name": "qwen3_8b",
    }


def client_for(module, data):
    client = MagicMock()
    response = MagicMock(status_code=200)
    response.json.return_value = data
    client.get.return_value = response
    client.put.return_value = response
    module.http_client_manager.get_sync_client.return_value = client
    return client


def test_forwarded_create_matches_live_contract(aidp_service_module, mock_aidp_server):
    module = aidp_service_module
    upstream = TestClient(mock_aidp_server.app)
    module.http_client_manager.get_sync_client.return_value = upstream
    result = module.create_aidp_kb_impl("http://testserver", "mock-aidp-key", {
        "name": "中文图谱知识库", "description": "中文测试资料",
        "embedding_model": "/models/bge-m3", "chunk_token_num": 512,
        "chunk_overlap_num": 51, "similarity": 0.6, "topk": 10,
        "is_exist_graph": True, "graph_config": graph_config(),
    })
    saved = upstream.get(
        f"{mock_aidp_server._KB_PREFIX}/{result['kds_id']}",
        headers={"Authorization": "Bearer mock-aidp-key"},
    ).json()
    assert json.loads(saved["graph_config"]) == graph_config()
    assert saved["embedding_model"] == "/models/bge-m3"
    assert saved["topk"] == 10 and saved["is_personal"] == 0
    assert saved["vlm_model"] == "" and saved["caption_enable"] == 0
    assert "smartsplit" not in saved


@pytest.mark.parametrize("key,value", [
    ("retrieve_default_topk", "5"), ("retrieve_topk", "5"),
    ("no_think_mode", True), ("synonym_merge_enable", False),
    ("disambiguation_enable", False), ("domain", "general"),
    ("prompt_language", "chinese"), ("retrieve_subgraph_hop", 2),
    ("prompt_text", ""), ("prompt_text", "字" * 4097),
])
def test_mock_rejects_the_live_failures(mock_aidp_server, key, value):
    config = graph_config()
    config[key] = value
    response = TestClient(mock_aidp_server.app).put(mock_aidp_server._KB_PREFIX,
        headers={"Authorization": "Bearer mock-aidp-key"},
        json={"name": "错误参数", "is_exist_graph": True,
              "graph_config": json.dumps(config, ensure_ascii=False)})
    assert response.status_code == 400


def test_prompt_limit_counts_characters_and_disabled_graph_omits_config(aidp_service_module):
    module = aidp_service_module
    config = graph_config()
    config["prompt_text"] = "字😀" * 2048
    serialized = json.loads(module._serialize_graph_config(config))
    assert len(serialized["prompt_text"]) == 4096
    config["prompt_text"] += "字"
    with pytest.raises(module.AppException):
        module._serialize_graph_config(config)
    disabled = module._apply_create_defaults(
        {
            "name": "无图谱",
            "description": "禁用知识图谱的测试知识库",
            "is_exist_graph": False,
            "graph_config": config,
        }
    )
    assert "graph_config" not in disabled


@pytest.mark.parametrize("language", ["chinese", "english"])
def test_template_query_and_model_query_use_single_endpoints(aidp_service_module, mock_aidp_server, language):
    module = aidp_service_module
    upstream = TestClient(mock_aidp_server.app)
    module.http_client_manager.get_sync_client.return_value = upstream
    template = module.get_aidp_graph_template_impl("http://testserver", "mock-aidp-key", language)
    assert len(template["value"]) == 7
    assert next(p for p in template["value"] if p["param_key"] == "prompt_text")["template"]["法律法规"]
    models = module.list_aidp_models_impl("http://testserver", "mock-aidp-key", "")
    assert {"llm", "vlm", "embedding"} <= {m["model_type"] for m in models["models"]}
    assert "doc-parser-only" not in {m["model_name"] for m in models["models"]}


def test_all_models_does_not_send_service_filter(aidp_service_module):
    client = client_for(aidp_service_module, {"models": []})
    aidp_service_module.list_aidp_models_impl("http://example.test", "key", "")
    assert "app=KnowledgeBase" in client.get.call_args.args[0]
    assert "service=" not in client.get.call_args.args[0]


@pytest.mark.parametrize("domain,expected", [
    ("常规", "不能使用代词"), ("医疗", "Disease (疾病)"),
    ("金融", "Stock (股票)"), ("法律法规", "Law (法律法规)"),
])
def test_chinese_template_returns_complete_captured_prompts(mock_aidp_server, domain, expected):
    response = TestClient(mock_aidp_server.app).get(
        f"{mock_aidp_server._KB_PREFIX}/GraphConfigTemplate?language=chinese",
        headers={"Authorization": "Bearer mock-aidp-key"},
    )
    assert response.status_code == 200
    parameter = next(p for p in response.json()["value"] if p["param_key"] == "prompt_text")
    text = parameter["template"][domain]
    assert 200 < len(text) <= 4096
    assert text.startswith("---Role---\n") and expected in text
    assert "关系" in text and text.count("\n") >= 10
    assert parameter["param_value"] == parameter["template"]["常规"]


def test_current_graph_config_values_are_serialized_without_aliases(aidp_service_module):
    config = {**graph_config(), "no_think_mode": "否", "retrieve_subgraph_hop": "3"}
    result = json.loads(aidp_service_module._serialize_graph_config(config))
    assert result["domain"] == "常规" and result["prompt_language"] == "中文"
    assert result["no_think_mode"] == "否" and result["retrieve_subgraph_hop"] == "3"
    assert "retrieve_default_topk" not in result and "retrieve_topk" not in result


@pytest.mark.parametrize(
    "key,value",
    [
        ("domain", "general"),
        ("prompt_language", "chinese"),
        ("no_think_mode", False),
        ("synonym_merge_enable", False),
        ("disambiguation_enable", False),
        ("retrieve_subgraph_hop", 3),
        ("retrieve_default_topk", "5"),
        ("retrieve_topk", "5"),
    ],
)
def test_legacy_graph_config_values_are_rejected(aidp_service_module, key, value):
    config = {**graph_config(), key: value}
    with pytest.raises(aidp_service_module.AppException):
        aidp_service_module._serialize_graph_config(config)

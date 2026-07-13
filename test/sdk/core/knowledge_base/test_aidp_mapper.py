import importlib.util
import sys
import types
from pathlib import Path


def _load_mapper_module():
    repo_root = Path(__file__).resolve().parents[4]
    package_dir = repo_root / "sdk" / "nexent" / "core" / "knowledge_base"
    packages = {
        "nexent": repo_root / "sdk" / "nexent",
        "nexent.core": repo_root / "sdk" / "nexent" / "core",
        "nexent.core.knowledge_base": package_dir,
    }
    for name, path in packages.items():
        module = sys.modules.get(name) or types.ModuleType(name)
        module.__path__ = [str(path)]
        sys.modules[name] = module

    for module_name in ("config", "mapper"):
        full_name = f"nexent.core.knowledge_base.{module_name}"
        spec = importlib.util.spec_from_file_location(full_name, package_dir / f"{module_name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[full_name] = module
        spec.loader.exec_module(module)
    return sys.modules["nexent.core.knowledge_base.mapper"]


mapper = _load_mapper_module()
build_create_payload = mapper.build_create_payload
build_retrieve_payload = mapper.build_retrieve_payload
map_document_list = mapper.map_document_list
map_knowledge_base_list = mapper.map_knowledge_base_list
map_retrieve_response = mapper.map_retrieve_response


def test_create_payload_fills_aidp_defaults():
    payload = build_create_payload({"name": "kb", "description": "desc"})

    assert payload["name"] == "kb"
    assert payload["description"] == "desc"
    assert payload["chunk_token_num"] == 1024
    assert payload["chunk_overlap_num"] == 128
    assert payload["embedding_model"] == "default"
    assert payload["is_personal"] == 0
    assert payload["caption_enable"] == 0


def test_knowledge_base_list_uses_count_for_has_more():
    raw = {
        "value": [
            {
                "kds_id": 1,
                "kds_name": "Public KB",
                "description": "docs",
                "state": 4,
                "create_time": 1_700_000_000,
            }
        ],
    }

    mapped = map_knowledge_base_list(raw, page=1, page_size=20, total_count=21)

    assert mapped["total"] == 21
    assert mapped["has_more"] is True
    assert mapped["list"][0]["id"] == "1"
    assert mapped["list"][0]["status"] == "active"


def test_retrieve_payload_maps_search_method_names():
    payload = build_retrieve_payload(
        {
            "query": "hello",
            "knowledge_base_ids": ["1"],
            "retrieval_model": {
                "search_method": "keyword_search",
                "top_k": 3,
                "score_threshold": 0.5,
                "score_threshold_enabled": True,
            },
        }
    )

    assert payload["kds_list"] == ["1"]
    assert payload["search_method"] == "full_text_search"
    assert payload["top_k"] == 3
    assert payload["score_threshold"] == 0.5


def test_document_list_generates_standard_document_shape():
    mapped = map_document_list(
        {
            "value": [
                {
                    "file_name": "manual.pdf",
                    "file_type": "pdf",
                    "file_size": 42,
                    "first_upload_time": 1_700_000_000,
                    "update_time": 1_700_000_100,
                    "import_source_dir": "/1",
                    "file_ino_no": 99,
                    "file_system_id": "fs1",
                }
            ],
            "total_count": 1,
        },
        knowledge_base_id="1",
        page=1,
        page_size=20,
    )

    doc = mapped["list"][0]
    assert doc["id"]
    assert doc["name"] == "manual.pdf"
    assert doc["status"] == "completed"
    assert doc["chunk_count"] == 0
    assert mapped["has_more"] is False


def test_retrieve_response_maps_aidp_chunks_to_standard_records():
    mapped = map_retrieve_response(
        {
            "result": [
                {
                    "id": 10,
                    "score": 0.8,
                    "title": "manual.pdf",
                    "text": "content",
                    "metadata": {"kds_id": "1", "kds_name": "KB"},
                }
            ]
        },
        query="hello",
        knowledge_base_ids=["1"],
    )

    assert mapped["query"] == "hello"
    assert mapped["records"][0]["score"] == 0.8
    assert mapped["records"][0]["segment"]["content"] == "content"
    assert mapped["records"][0]["segment"]["knowledge_base_id"] == "1"

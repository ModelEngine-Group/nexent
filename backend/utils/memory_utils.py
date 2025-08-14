import logging
from typing import Dict, Any
from urllib.parse import urlparse

from consts import const as _c
from utils.config_utils import get_model_name_from_config, tenant_config_manager

logger = logging.getLogger("memory_utils")


def build_memory_config(tenant_id: str) -> Dict[str, Any]:
    """Return a fully-validated configuration dictionary for *mem0* ``Memory``.
    """
    # 1. Resolve tenant-specific model configuration
    llm_raw = tenant_config_manager.get_model_config("LLM_ID", tenant_id=tenant_id)
    embed_raw = tenant_config_manager.get_model_config("EMBEDDING_ID", tenant_id=tenant_id)

    if not (llm_raw and llm_raw.get("model_name")):
        raise ValueError("Missing LLM configuration for tenant")
    if not (embed_raw and embed_raw.get("max_tokens")):
        raise ValueError("Missing embedding-model configuration for tenant")

    # 2. Resolve Elasticsearch connection details
    if not _c.ES_HOST:
        raise ValueError("ES_HOST is not configured")
    parsed = urlparse(_c.ES_HOST)
    if not (parsed.scheme and parsed.hostname and parsed.port):
        raise ValueError("ES_HOST must include scheme, host and port, e.g. http://host:9200")
    es_host = f"{parsed.scheme}://{parsed.hostname}"
    es_port = parsed.port

    # 3. Assemble final configuration
    memory_config: Dict[str, Any] = {
        "llm": {
            "provider": "openai",
            "config": {
                "model": get_model_name_from_config(llm_raw),
                "openai_base_url": llm_raw["base_url"],
                "api_key": llm_raw["api_key"],
            },
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": get_model_name_from_config(embed_raw),
                "openai_base_url": embed_raw["base_url"],
                "embedding_dims": embed_raw["max_tokens"],
                "api_key": embed_raw["api_key"],
            },
        },
        "vector_store": {
            "provider": "elasticsearch",
            "config": {
                "collection_name": "mem0",
                "host": es_host,
                "port": es_port,
                "embedding_model_dims": embed_raw["max_tokens"],
                "verify_certs": False,
                "api_key": _c.ES_API_KEY,
                "user": _c.ES_USERNAME,
                "password": _c.ES_PASSWORD,
            },
        },
        "telemetry": {"enabled": False},
    }
    return memory_config 
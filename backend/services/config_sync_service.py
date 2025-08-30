import logging

from fastapi.responses import JSONResponse

from consts.const import DEFAULT_APP_NAME_ZH, DEFAULT_APP_NAME_EN, DEFAULT_APP_DESCRIPTION_ZH, \
    DEFAULT_APP_DESCRIPTION_EN, DEFAULT_APP_ICON_URL
from database.model_management_db import get_model_id_by_display_name
from utils.config_utils import tenant_config_manager, get_env_key, safe_value, config_manager, \
    get_model_name_from_config

logger = logging.getLogger("config_sync_service")


def handle_model_config(tenant_id: str, user_id: str, config_key: str, model_id: int, tenant_config_dict: dict) -> None:
    """
    Handle model configuration updates, deletions, and settings operations

    Args:
        tenant_id: Tenant ID
        user_id: User ID
        config_key: Configuration key name
        model_id: Model ID
        tenant_config_dict: Tenant configuration dictionary
    """
    if not model_id and config_key in tenant_config_dict:
        tenant_config_manager.delete_single_config(tenant_id, config_key)
    elif config_key in tenant_config_dict:
        try:
            existing_model_id = int(
                tenant_config_dict[config_key]) if tenant_config_dict[config_key] else None
            if existing_model_id == model_id:
                tenant_config_manager.update_single_config(
                    tenant_id, config_key)
            else:
                tenant_config_manager.delete_single_config(
                    tenant_id, config_key)
                if model_id:
                    tenant_config_manager.set_single_config(
                        user_id, tenant_id, config_key, model_id)
        except (ValueError, TypeError):
            tenant_config_manager.delete_single_config(tenant_id, config_key)
            if model_id:
                tenant_config_manager.set_single_config(
                    user_id, tenant_id, config_key, model_id)
    else:
        if model_id:
            tenant_config_manager.set_single_config(
                user_id, tenant_id, config_key, model_id)


async def save_config_impl(config, tenant_id, user_id):
    config_dict = config.model_dump(exclude_none=False)
    env_config = {}
    tenant_config_dict = tenant_config_manager.load_config(tenant_id)
    # Process app configuration - use key names directly without prefix
    for key, value in config_dict.get("app", {}).items():
        env_key = get_env_key(key)
        env_config[env_key] = safe_value(value)

        # Check if the key exists and has the same value in tenant_config_dict
        if env_key in tenant_config_dict and tenant_config_dict[env_key] == safe_value(value):
            tenant_config_manager.update_single_config(tenant_id, env_key)
        elif env_key in tenant_config_dict and env_config[env_key] == '':
            tenant_config_manager.delete_single_config(tenant_id, env_key)
        elif env_key in tenant_config_dict:
            tenant_config_manager.delete_single_config(tenant_id, env_key)
            tenant_config_manager.set_single_config(
                user_id, tenant_id, env_key, safe_value(value))
        else:
            if env_config[env_key] not in [DEFAULT_APP_NAME_ZH, DEFAULT_APP_NAME_EN, DEFAULT_APP_DESCRIPTION_ZH,
                                           DEFAULT_APP_DESCRIPTION_EN]:
                tenant_config_manager.set_single_config(
                    user_id, tenant_id, env_key, safe_value(value))
    # Process model configuration
    for model_type, model_config in config_dict.get("models", {}).items():
        if not model_config:
            continue

        model_name = model_config.get("modelName")
        model_display_name = model_config.get("displayName")

        config_key = get_env_key(model_type) + "_ID"
        model_id = get_model_id_by_display_name(
            model_display_name, tenant_id)

        if not model_name:
            continue

        handle_model_config(tenant_id, user_id, config_key,
                            model_id, tenant_config_dict)

        model_prefix = get_env_key(model_type)

        # Still keep EMBEDDING_API_KEY in env
        if model_type == "embedding":
            if model_config and "apiConfig" in model_config:
                embedding_api_config = model_config.get("apiConfig", {})
                env_config[f"{model_prefix}_API_KEY"] = safe_value(
                    embedding_api_config.get("apiKey"))
    # Batch update environment variables
    for key, value in env_config.items():
        config_manager.set_config(key, value)
    logger.info("Configuration saved successfully")
    return JSONResponse(
        status_code=200,
        content={"message": "Configuration saved successfully",
                 "status": "saved"}
    )


async def load_config_impl(language, tenant_id):
    llm_model_name = tenant_config_manager.get_model_config(
        "LLM_ID", tenant_id=tenant_id)
    llm_secondary_model_name = tenant_config_manager.get_model_config(
        "LLM_SECONDARY_ID", tenant_id=tenant_id)
    embedding_model_name = tenant_config_manager.get_model_config(
        "EMBEDDING_ID", tenant_id=tenant_id)
    multi_embedding_model_name = tenant_config_manager.get_model_config(
        "MULTI_EMBEDDING_ID", tenant_id=tenant_id)
    rerank_model_name = tenant_config_manager.get_model_config(
        "RERANK_ID", tenant_id=tenant_id)
    vlm_model_name = tenant_config_manager.get_model_config(
        "VLM_ID", tenant_id=tenant_id)
    stt_model_name = tenant_config_manager.get_model_config(
        "STT_ID", tenant_id=tenant_id)
    tts_model_name = tenant_config_manager.get_model_config(
        "TTS_ID", tenant_id=tenant_id)
    default_app_name = DEFAULT_APP_NAME_ZH if language == "zh" else DEFAULT_APP_NAME_EN
    default_app_description = DEFAULT_APP_DESCRIPTION_ZH if language == "zh" else DEFAULT_APP_DESCRIPTION_EN
    config = {
        "app": {
            "name": tenant_config_manager.get_app_config("APP_NAME", tenant_id=tenant_id) or default_app_name,
            "description": tenant_config_manager.get_app_config("APP_DESCRIPTION",
                                                                tenant_id=tenant_id) or default_app_description,
            "icon": {
                "type": tenant_config_manager.get_app_config("ICON_TYPE", tenant_id=tenant_id) or "preset",
                "avatarUri": tenant_config_manager.get_app_config("AVATAR_URI",
                                                                  tenant_id=tenant_id) or DEFAULT_APP_ICON_URL,
                "customUrl": tenant_config_manager.get_app_config("CUSTOM_ICON_URL", tenant_id=tenant_id) or ""
            }
        },
        "models": {
            "llm": {
                "name": get_model_name_from_config(llm_model_name) if llm_model_name else "",
                "displayName": llm_model_name.get("display_name", ""),
                "apiConfig": {
                    "apiKey": llm_model_name.get("api_key", ""),
                    "modelUrl": llm_model_name.get("base_url", "")
                }
            },
            "llmSecondary": {
                "name": get_model_name_from_config(llm_secondary_model_name) if llm_secondary_model_name else "",
                "displayName": llm_secondary_model_name.get("display_name", ""),
                "apiConfig": {
                    "apiKey": llm_secondary_model_name.get("api_key", ""),
                    "modelUrl": llm_secondary_model_name.get("base_url", "")
                }
            },
            "embedding": {
                "name": get_model_name_from_config(embedding_model_name) if embedding_model_name else "",
                "displayName": embedding_model_name.get("display_name", ""),
                "apiConfig": {
                    "apiKey": embedding_model_name.get("api_key", ""),
                    "modelUrl": embedding_model_name.get("base_url", "")
                },
                "dimension": embedding_model_name.get("max_tokens", 0)
            },
            "multiEmbedding": {
                "name": get_model_name_from_config(
                    multi_embedding_model_name) if multi_embedding_model_name else "",
                "displayName": multi_embedding_model_name.get("display_name", ""),
                "apiConfig": {
                    "apiKey": multi_embedding_model_name.get("api_key", ""),
                    "modelUrl": multi_embedding_model_name.get("base_url", "")
                },
                "dimension": multi_embedding_model_name.get("max_tokens", 0)
            },
            "rerank": {
                "name": get_model_name_from_config(rerank_model_name) if rerank_model_name else "",
                "displayName": rerank_model_name.get("display_name", ""),
                "apiConfig": {
                    "apiKey": rerank_model_name.get("api_key", ""),
                    "modelUrl": rerank_model_name.get("base_url", "")
                }
            },
            "vlm": {
                "name": get_model_name_from_config(vlm_model_name) if vlm_model_name else "",
                "displayName": vlm_model_name.get("display_name", ""),
                "apiConfig": {
                    "apiKey": vlm_model_name.get("api_key", ""),
                    "modelUrl": vlm_model_name.get("base_url", "")
                }
            },
            "stt": {
                "name": get_model_name_from_config(stt_model_name) if stt_model_name else "",
                "displayName": stt_model_name.get("display_name", ""),
                "apiConfig": {
                    "apiKey": stt_model_name.get("api_key", ""),
                    "modelUrl": stt_model_name.get("base_url", "")
                }
            },
            "tts": {
                "name": get_model_name_from_config(tts_model_name) if tts_model_name else "",
                "displayName": tts_model_name.get("display_name", ""),
                "apiConfig": {
                    "apiKey": tts_model_name.get("api_key", ""),
                    "modelUrl": tts_model_name.get("base_url", "")
                }
            }
        }
    }
    return JSONResponse(
        status_code=200,
        content={"config": config}
    )

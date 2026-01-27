import logging
from typing import Optional

from consts.const import (
    APP_DESCRIPTION,
    APP_NAME,
    AVATAR_URI,
    CUSTOM_ICON_URL,
    DEFAULT_APP_DESCRIPTION_EN,
    DEFAULT_APP_DESCRIPTION_ZH,
    DEFAULT_APP_NAME_EN,
    DEFAULT_APP_NAME_ZH,
    ICON_TYPE,
    MODEL_CONFIG_MAPPING,
    LANGUAGE
)
from database.model_management_db import get_model_id_by_display_name
from utils.config_utils import (
    get_env_key,
    get_model_name_from_config,
    safe_value,
    tenant_config_manager
)

logger = logging.getLogger("config_sync_service")


def handle_model_config(tenant_id: str, user_id: str, config_key: str, model_id: Optional[int], tenant_config_dict: dict) -> None:
    """
    Handle model configuration updates, deletions, and settings operations

    Args:
        tenant_id: Tenant ID
        user_id: User ID
        config_key: Configuration key name
        model_id: Model ID
        tenant_config_dict: Tenant configuration dictionary
    """
    # Delete the config if the model_id is None
    if model_id is None:
        if config_key in tenant_config_dict:
            tenant_config_manager.delete_single_config(tenant_id, config_key)
        return

    # If the config key does not exist, set directly
    if config_key not in tenant_config_dict:
        tenant_config_manager.set_single_config(
            user_id, tenant_id, config_key, model_id)
        return

    current_model_id = tenant_config_dict.get(config_key)
    current_model_id = int(current_model_id) if str(current_model_id).isdigit() else None

    if current_model_id == model_id:
        tenant_config_manager.update_single_config(tenant_id, config_key)
        return

    # Delete the config first, then set the new value
    tenant_config_manager.delete_single_config(tenant_id, config_key)
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

        model_display_name = model_config.get("displayName")

        config_key = get_env_key(model_type) + "_ID"
        model_id = get_model_id_by_display_name(
            model_display_name, tenant_id)

        handle_model_config(tenant_id, user_id, config_key,
                            model_id, tenant_config_dict)

        model_prefix = get_env_key(model_type)

        # Still keep EMBEDDING_API_KEY in env
        if model_type == "embedding":
            if model_config and "apiConfig" in model_config:
                embedding_api_config = model_config.get("apiConfig", {})
                env_config[f"{model_prefix}_API_KEY"] = safe_value(
                    embedding_api_config.get("apiKey"))
    logger.info("Configuration saved successfully")


async def load_config_impl(language: str, tenant_id: str):
    try:
        config = {
            "app": build_app_config(language, tenant_id),
            "models": build_models_config(tenant_id)
        }
        return config
    except Exception as e:
        logger.error(f"Failed to load config for tenant {tenant_id}: {e}")
        raise Exception(f"Failed to load config for tenant {tenant_id}.")


def build_app_config(language: str, tenant_id: str) -> dict:
    default_app_name = DEFAULT_APP_NAME_ZH if language == LANGUAGE["ZH"] else DEFAULT_APP_NAME_EN
    default_app_description = DEFAULT_APP_DESCRIPTION_ZH if language == LANGUAGE[
        "ZH"] else DEFAULT_APP_DESCRIPTION_EN

    return {
        "name": tenant_config_manager.get_app_config(APP_NAME, tenant_id=tenant_id) or default_app_name,
        "description": tenant_config_manager.get_app_config(APP_DESCRIPTION,
                                                            tenant_id=tenant_id) or default_app_description,
        "icon": {
            "type": tenant_config_manager.get_app_config(ICON_TYPE, tenant_id=tenant_id) or "preset",
            "avatarUri": tenant_config_manager.get_app_config(AVATAR_URI, tenant_id=tenant_id) or "",
            "customUrl": tenant_config_manager.get_app_config(CUSTOM_ICON_URL, tenant_id=tenant_id) or ""
        }
    }


def build_models_config(tenant_id: str) -> dict:
    models_config = {}

    for model_key, config_key in MODEL_CONFIG_MAPPING.items():
        try:
            model_config = tenant_config_manager.get_model_config(
                config_key, tenant_id=tenant_id)
            models_config[model_key] = build_model_config(model_config)
        except Exception as e:
            logger.warning(f"Failed to get config for {config_key}: {e}")
            models_config[model_key] = build_model_config({})

    return models_config


def build_model_config(model_config: dict) -> dict:
    if not model_config:
        return {
            "name": "",
            "displayName": "",
            "apiConfig": {
                "apiKey": "",
                "modelUrl": ""
            }
        }

    config = {
        "name": get_model_name_from_config(model_config) if model_config else "",
        "displayName": model_config.get("display_name", ""),
        "apiConfig": {
            "apiKey": model_config.get("api_key", ""),
            "modelUrl": model_config.get("base_url", "")
        }
    }

    if "embedding" in model_config.get("model_type", ""):
        config["dimension"] = model_config.get("max_tokens", 0)

    return config

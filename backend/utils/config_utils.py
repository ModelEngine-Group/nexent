import json
import logging
from typing import Dict, Any

from sqlalchemy.sql import func

from database.model_management_db import get_model_by_model_id
from database.tenant_config_db import (
    delete_config_by_tenant_config_id,
    get_all_configs_by_tenant_id,
    get_single_config_info,
    insert_config,
    update_config_by_tenant_config_id_and_data,
)

logger = logging.getLogger("config_utils")


def safe_value(value):
    """Helper function for processing configuration values"""
    if value is None:
        return ""
    return str(value)


def safe_list(value):
    """Helper function for processing list values, using JSON format for storage to facilitate parsing"""
    if not value:
        return "[]"
    return json.dumps(value)


def get_env_key(key: str) -> str:
    """Helper function for generating environment variable key names"""
    # Convert camelCase to snake_case format
    import re
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', key)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).upper()


def get_model_name_from_config(model_config: Dict[str, Any]) -> str:
    """Get model name from model id"""
    if model_config is None:
        return ""
    model_repo = model_config["model_repo"]
    model_name = model_config["model_name"]
    if not model_repo:
        return model_name
    return f"{model_repo}/{model_name}"


class TenantConfigManager:
    """Tenant configuration manager that reads configurations from the database on demand."""

    def load_config(self, tenant_id: str, force_reload: bool = False):
        """Load configuration from database and update cache

        Args:
            tenant_id (str): The tenant ID to load configurations for
            force_reload (bool): Force reload from database ignoring cache

        Returns:
            dict: The current configuration cache for the tenant
        """
        # Check if tenant_id is valid
        if not tenant_id:
            logger.warning("Invalid tenant ID provided")
            return {}

        # Always load latest configurations directly from DB (no in-process cache).
        configs = get_all_configs_by_tenant_id(tenant_id)

        if not configs:
            logger.info(f"No configurations found for tenant {tenant_id}")
            return {}

        tenant_configs = {}
        for config in configs:
            tenant_configs[config["config_key"]] = config["config_value"]

        return tenant_configs

    def get_model_config(self, key: str, default=None, tenant_id: str | None = None):
        if default is None:
            default = {}
        if tenant_id is None:
            logger.warning(
                f"No tenant_id specified when getting config for key: {key}")
            return default
        tenant_config = self.load_config(tenant_id)

        if key in tenant_config:
            model_id = tenant_config[key]
            if not model_id:  # Check if model_id is empty
                return default
            try:
                model_config = get_model_by_model_id(
                    model_id=int(model_id), tenant_id=tenant_id)
                return model_config if model_config else default
            except (ValueError, TypeError):
                logger.warning(f"Invalid model_id format: {model_id}")
                return default
        return default

    def get_app_config(self, key: str, default="", tenant_id: str | None = None):
        if tenant_id is None:
            logger.warning(
                f"No tenant_id specified when getting config for key: {key}")
            return default
        tenant_config = self.load_config(tenant_id)
        if key in tenant_config:
            return tenant_config[key]
        return default

    def set_single_config(self, user_id: str | None = None, tenant_id: str | None = None, key: str | None = None,
                          value: str | None = None, ):
        """Set configuration value in database with caching"""
        if tenant_id is None:
            logger.warning(
                f"No tenant_id specified when setting config for key: {key}")
            return

        insert_data = {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "config_key": key,
            "value_type": "single",
            "config_value": value if value else "",
            "delete_flag": "N",
            "created_by": tenant_id,
            "updated_by": tenant_id,
            "create_time": func.current_timestamp(),
        }

        insert_config(insert_data)

    def delete_single_config(self, tenant_id: str | None = None, key: str | None = None, ):
        """Delete configuration value in database"""
        if tenant_id is None:
            logger.warning(
                f"No tenant_id specified when deleting config for key: {key}")
            return

        existing_config = get_single_config_info(tenant_id, key)
        if existing_config:
            delete_config_by_tenant_config_id(
                existing_config["tenant_config_id"])
            return

    def update_single_config(self, tenant_id: str | None = None, key: str | None = None):
        """Update configuration value in database"""
        if tenant_id is None:
            logger.warning(
                f"No tenant_id specified when updating config for key: {key}")
            return

        existing_config = get_single_config_info(tenant_id, key)
        if existing_config:
            update_data = {
                "updated_by": tenant_id,
                "update_time": func.current_timestamp()
            }
            update_config_by_tenant_config_id_and_data(
                existing_config["tenant_config_id"], update_data)
            return


tenant_config_manager = TenantConfigManager()

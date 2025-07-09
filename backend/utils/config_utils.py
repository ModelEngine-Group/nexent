import json
import os
import time
import logging

from dotenv import load_dotenv, set_key
from typing import Dict, Any
from sqlalchemy.sql import func
from database.tenant_config_db import get_all_configs_by_tenant_id, insert_config, delete_config_by_tenant_config_id, update_config_by_tenant_config_id_and_data, get_single_config_info
from database.model_management_db import get_model_by_model_id

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

class ConfigManager:
    """Configuration manager for dynamic loading and caching configurations"""

    def __init__(self, env_file=".env"):
        self.env_file = env_file
        self.last_modified_time = 0
        self.config_cache = {}
        self.load_config()

    def load_config(self):
        """Load configuration file and update cache"""
        # Check if file exists
        if not os.path.exists(self.env_file):
            logger.warning(f"Configuration file {self.env_file} does not exist")
            return

        # Get file last modification time
        current_mtime = os.path.getmtime(self.env_file)

        # If file hasn't been modified, return directly
        if current_mtime == self.last_modified_time:
            return

        # Update last modification time
        self.last_modified_time = current_mtime

        # Reload configuration
        load_dotenv(self.env_file, override=True)

        # Update cache
        self.config_cache = {key: value for key, value in os.environ.items()}
        logger.info(f"Configuration reloaded at: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    def get_config(self, key, default=""):
        """Get configuration value, reload if configuration has been updated"""
        self.load_config()
        return self.config_cache.get(key, default)

    def set_config(self, key, value):
        """Set configuration value"""
        self.config_cache[key] = value
        set_key(self.env_file, key, value)

    def force_reload(self):
        """Force reload configuration"""
        self.last_modified_time = 0
        self.load_config()
        return {"status": "success", "message": "Configuration reloaded"}

# Create global configuration manager instance
_current_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_env_file = os.path.join(_current_dir, ".env")
config_manager = ConfigManager(_env_file)


class TenantConfigManager:
    """Tenant configuration manager for dynamic loading and caching configurations from database"""

    def __init__(self):
        self.config_cache = {}
        self.cache_expiry = {}  # Store expiration timestamps for each cache entry
        self.CACHE_DURATION = 86400  # 1 day in seconds
        self.last_modified_times = {}  # Store last modified times for each tenant

    def _get_cache_key(self, tenant_id: str, key: str) -> str:
        """Generate a unique cache key combining tenant_id and key"""
        return f"{tenant_id}:{key}"

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

        complete_cache_key = self._get_cache_key(tenant_id, "*")
        current_time = time.time()

        # Check if we have a valid cache entry
        if not force_reload and complete_cache_key in self.config_cache:
            # Check if cache is still valid
            if complete_cache_key in self.cache_expiry and current_time < self.cache_expiry[complete_cache_key]:
                return self.config_cache[complete_cache_key]

        # Cache miss or forced reload - Get configurations from database
        configs = get_all_configs_by_tenant_id(tenant_id)

        if not configs:
            logger.warning(f"No configurations found for tenant {tenant_id}")
            return {}

        # Update cache with new configurations
        cache_updates = 0
        tenant_configs = {}

        for config in configs:
            cache_key = self._get_cache_key(tenant_id, config["config_key"])
            self.config_cache[cache_key] = config["config_value"]
            tenant_configs[config["config_key"]] = config["config_value"]
            self.cache_expiry[cache_key] = current_time + self.CACHE_DURATION
            cache_updates += 1

        # Store the complete tenant config
        self.config_cache[complete_cache_key] = tenant_configs
        self.cache_expiry[complete_cache_key] = current_time + self.CACHE_DURATION

        # Store the last modified time from database
        self.last_modified_times[tenant_id] = self._get_tenant_config_modified_time(tenant_id)

        logger.info(f"Configuration reloaded for tenant {tenant_id} at: {time.strftime('%Y-%m-%d %H:%M:%S')}")

        return tenant_configs

    def _get_tenant_config_modified_time(self, tenant_id: str) -> float:
        """Get the last modification time of tenant configurations

        Args:
            tenant_id (str): The tenant ID to check

        Returns:
            float: The last modification timestamp
        """
        # This is a placeholder - implement actual database query
        # to get the last modification time of tenant configurations
        # Example: return db.query("SELECT MAX(modified_at) FROM tenant_configs WHERE tenant_id = %s", tenant_id)
        return time.time()  # Temporary implementation

    def get_model_config(self, key: str, default=None, tenant_id: str | None = None):
        if default is None:
            default = {}
        if tenant_id is None:
            logger.warning(f"No tenant_id specified when getting config for key: {key}")
            return default
        tenant_config = self.load_config(tenant_id)
        
        if key in tenant_config:
            model_id = tenant_config[key]
            if not model_id:  # Check if model_id is empty
                return default
            try:
                model_config = get_model_by_model_id(model_id=int(model_id), tenant_id=tenant_id)
                return model_config if model_config else default
            except (ValueError, TypeError):
                logger.warning(f"Invalid model_id format: {model_id}")
                return default
        return default

    def get_app_config(self, key: str, default="", tenant_id: str | None = None):
        if tenant_id is None:
            logger.warning(f"No tenant_id specified when getting config for key: {key}")
            return default
        tenant_config = self.load_config(tenant_id)
        if key in tenant_config:
            return tenant_config[key]
        return default

    def set_single_config(self, user_id: str | None = None, tenant_id: str | None = None, key: str | None = None,
                          value: str | None = None, ):
        """Set configuration value in database with caching"""
        if tenant_id is None:
            logger.warning(f"No tenant_id specified when setting config for key: {key}")
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
        # Clear cache for this tenant after setting new config
        self.clear_cache(tenant_id)

    def delete_single_config(self, tenant_id: str | None = None, key: str | None = None, ):
        """Delete configuration value in database"""
        if tenant_id is None:
            logger.warning(f"No tenant_id specified when deleting config for key: {key}")
            return

        existing_config = get_single_config_info(tenant_id, key)
        if existing_config:
            delete_config_by_tenant_config_id(existing_config["tenant_config_id"])
            # Clear cache for this tenant after deleting config
            self.clear_cache(tenant_id)
            return

    def update_single_config(self, tenant_id: str | None = None, key: str | None = None):
        """Update configuration value in database"""
        if tenant_id is None:
            logger.warning(f"No tenant_id specified when updating config for key: {key}")
            return

        existing_config = get_single_config_info(tenant_id, key)
        if existing_config:
            update_data = {
                "updated_by": tenant_id,
                "update_time": func.current_timestamp()
            }
            update_config_by_tenant_config_id_and_data(existing_config["tenant_config_id"], update_data)
            
            # Clear cache for this tenant after updating config
            # self.clear_cache(tenant_id)
            return

    def clear_cache(self, tenant_id: str | None = None):
        """Clear the cache for a specific tenant or all tenants"""
        if tenant_id:
            # Clear cache for specific tenant
            keys_to_remove = [k for k in self.config_cache.keys() if k.startswith(f"{tenant_id}:")]
            for key in keys_to_remove:
                del self.config_cache[key]
                if key in self.cache_expiry:
                    del self.cache_expiry[key]
        else:
            # Clear all cache
            self.config_cache.clear()
            self.cache_expiry.clear()


tenant_config_manager = TenantConfigManager()
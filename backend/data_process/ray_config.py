"""
Ray configuration management module
"""

import logging
import os
from typing import Any, Dict, Optional

import ray

from consts.const import (
    RAY_NUM_CPUS,
    RAY_OBJECT_STORE_MEMORY_GB,
    RAY_PLASMA_DIRECTORY,
    RAY_TEMP_DIR,
)

logger = logging.getLogger("data_process.ray_config")

# Forward declaration variable so runtime references succeed before instantiation
ray_config: Optional["RayConfig"] = None


class RayConfig:
    """Ray configuration manager"""

    def __init__(self):
        self.plasma_directory = RAY_PLASMA_DIRECTORY
        self.object_store_memory_gb = RAY_OBJECT_STORE_MEMORY_GB
        self.temp_dir = RAY_TEMP_DIR

    def get_init_params(
            self,
            address: Optional[str] = None,
            num_cpus: Optional[int] = None,
            include_dashboard: bool = False,
            dashboard_host: str = "0.0.0.0",
            dashboard_port: int = 8265
    ) -> Dict[str, Any]:
        """
        Get Ray initialization parameters

        Args:
            address: Ray cluster address, None means start local cluster
            num_cpus: Number of CPU cores
            include_dashboard: Whether to include dashboard
            dashboard_host: Dashboard host address
            dashboard_port: Dashboard port

        Returns:
            Ray initialization parameters dictionary
        """
        params = {
            "ignore_reinit_error": True,
            "_plasma_directory": self.plasma_directory,
        }

        if address:
            params["address"] = address
        else:
            # Local cluster configuration
            if num_cpus:
                params["num_cpus"] = num_cpus

            # Object store memory configuration (convert to bytes)
            object_store_memory = int(
                self.object_store_memory_gb * 1024 * 1024 * 1024)
            params["object_store_memory"] = object_store_memory

            # Temp directory configuration
            params["_temp_dir"] = self.temp_dir

            # Dashboard configuration
            if include_dashboard:
                params["include_dashboard"] = True
                params["dashboard_host"] = dashboard_host
                params["dashboard_port"] = dashboard_port

        return params

    def init_ray(self, **kwargs) -> bool:
        """
        Initialize Ray

        Args:
            **kwargs: Parameters passed to get_init_params

        Returns:
            Whether initialization is successful
        """
        try:
            if ray.is_initialized():
                logger.info("Ray already initialized, skipping...")
                return True

            params = self.get_init_params(**kwargs)

            # Log the attempt to initialize
            logger.debug("Initializing Ray cluster...")
            logger.debug("Ray configuration parameters:")
            for key, value in params.items():
                if key.startswith('_'):
                    logger.debug(f"  {key}: {value}")
                elif key == 'object_store_memory':
                    logger.debug(f"  {key}: {value / (1024 ** 3):.1f} GB")
                else:
                    logger.debug(f"  {key}: {value}")

            ray.init(**params)
            logger.info("✅ Ray initialization successful")

            # Display cluster information
            try:
                if hasattr(ray, 'cluster_resources'):
                    resources = ray.cluster_resources()
                    logger.debug(f"Ray cluster resources: {resources}")
            except Exception as e:
                logger.error(
                    f"Failed to get cluster resources information: {e}")

            return True

        except Exception as e:
            logger.error(f"❌ Ray initialization failed: {str(e)}")
            return False

    def connect_to_cluster(self, address: str = "auto") -> bool:
        """
        Connect to existing Ray cluster

        Args:
            address: Cluster address, 'auto' means auto-discovery

        Returns:
            Whether connection is successful
        """
        try:
            if ray.is_initialized():
                logger.debug("Ray already initialized, skipping...")
                return True

            params = self.get_init_params(address=address)

            logger.debug(f"Connecting to Ray cluster: {address}")
            ray.init(**params)
            logger.info("✅ Successfully connected to Ray cluster")

            return True

        except Exception as e:
            logger.info(f"Cannot connect to Ray cluster: {str(e)}")
            return False

    def start_local_cluster(
            self,
            num_cpus: Optional[int] = None,
            include_dashboard: bool = True,
            dashboard_port: int = 8265
    ) -> bool:
        """
        Start local Ray cluster

        Args:
            num_cpus: Number of CPU cores, None means using all available cores
            include_dashboard: Whether to start dashboard
            dashboard_port: Dashboard port

        Returns:
            Whether initialization is successful
        """
        if num_cpus is None:
            num_cpus = os.cpu_count()

        return self.init_ray(
            num_cpus=num_cpus,
            include_dashboard=include_dashboard,
            dashboard_port=dashboard_port
        )

    def log_configuration(self):
        """Log current configuration information"""
        logger.debug("Ray Configuration:")
        logger.debug(f"  Plasma directory: {self.plasma_directory}")
        logger.debug(f"  ObjectStore memory: {self.object_store_memory_gb} GB")
        logger.debug(f"  Temp directory: {self.temp_dir}")

    @classmethod
    def init_ray_for_worker(cls, address: str = "auto") -> bool:
        """Initialize Ray connection for Celery Worker (class method wrapper)."""
        logger.info("Initialize Ray connection for Celery Worker...")
        ray_config.log_configuration()
        return ray_config.connect_to_cluster(address)

    @classmethod
    def init_ray_for_service(
            cls,
            num_cpus: Optional[int] = None,
            dashboard_port: int = 8265,
            try_connect_first: bool = True,
            include_dashboard: bool = True
    ) -> bool:
        """Initialize Ray for data processing service (class method wrapper)."""
        ray_config.log_configuration()

        if try_connect_first:
            # Try to connect to existing cluster first
            logger.debug("Trying to connect to existing Ray cluster...")
            if ray_config.connect_to_cluster("auto"):
                return True
            logger.info("Starting local cluster...")

        # Start local cluster
        return ray_config.start_local_cluster(
            num_cpus=num_cpus,
            include_dashboard=include_dashboard,
            dashboard_port=dashboard_port
        )

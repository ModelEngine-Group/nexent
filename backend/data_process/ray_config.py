"""
Ray configuration management module
"""

import logging
import os
from typing import Any, Dict, Optional

import ray

from consts.const import (
    RAY_OBJECT_STORE_MEMORY_GB,
    RAY_TEMP_DIR,
    RAY_preallocate_plasma,
)

logger = logging.getLogger("data_process.ray_config")

# Forward declaration variable so runtime references succeed before instantiation
ray_config: Optional["RayConfig"] = None


class RayConfig:
    """Ray configuration manager"""

    def __init__(self):
        self.object_store_memory_gb = RAY_OBJECT_STORE_MEMORY_GB
        self.temp_dir = RAY_TEMP_DIR
        self.preallocate_plasma = RAY_preallocate_plasma

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

            # Object spilling directory (stable API)
            # This allows Ray to spill objects to disk when memory is full
            params["object_spilling_directory"] = self.temp_dir

            # Dashboard configuration
            # Always pass include_dashboard explicitly because Ray's default is True.
            # If we omit this parameter when include_dashboard is False,
            # Ray will still start the dashboard by default.
            params["include_dashboard"] = include_dashboard
            if include_dashboard:
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

            # Set RAY_preallocate_plasma environment variable before initialization
            # Ray reads this environment variable during initialization
            os.environ["RAY_preallocate_plasma"] = str(
                self.preallocate_plasma).lower()

            params = self.get_init_params(**kwargs)

            # Log the attempt to initialize
            logger.info("Initializing Ray cluster...")
            logger.info("Ray memory optimization configuration:")
            logger.info(
                f"  RAY_preallocate_plasma: {self.preallocate_plasma}")
            logger.info(
                f"  Object store memory: {self.object_store_memory_gb} GB")
            for key, value in params.items():
                if key.startswith('_'):
                    logger.debug(f"  {key}: {value}")
                elif key == 'object_store_memory':
                    logger.info(f"  {key}: {value / (1024 ** 3):.2f} GB")
                elif key == 'object_spilling_directory':
                    logger.info(f"  {key}: {value}")
                else:
                    logger.debug(f"  {key}: {value}")

            ray.init(**params)
            logger.info("✅ Ray initialization successful")

            # Display cluster information and verify memory configuration
            try:
                if hasattr(ray, 'cluster_resources'):
                    resources = ray.cluster_resources()
                    logger.info(f"Ray cluster resources: {resources}")

                    # Log memory-related resources
                    if 'memory' in resources:
                        logger.info(
                            f"  Total cluster memory: {resources['memory'] / (1024**3):.2f} GB")
                    if 'object_store_memory' in resources:
                        logger.info(
                            f"  Object store memory: {resources['object_store_memory'] / (1024**3):.2f} GB")
            except Exception as e:
                logger.warning(
                    f"Could not retrieve cluster resources information: {e}")

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

            # Set RAY_preallocate_plasma environment variable before initialization
            # Note: When connecting to existing cluster, this setting may not take effect
            # as the cluster was already initialized with its own settings
            os.environ["RAY_preallocate_plasma"] = str(
                self.preallocate_plasma).lower()

            params = self.get_init_params(address=address)

            logger.debug(f"Connecting to Ray cluster: {address}")
            logger.debug(
                f"  RAY_preallocate_plasma: {self.preallocate_plasma}")
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
        logger.debug(f"  ObjectStore memory: {self.object_store_memory_gb} GB")
        logger.debug(f"  Temp directory: {self.temp_dir}")
        logger.debug(f"  Preallocate plasma: {self.preallocate_plasma}")

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


# Create a global RayConfig instance accessible throughout the module
ray_config = RayConfig()

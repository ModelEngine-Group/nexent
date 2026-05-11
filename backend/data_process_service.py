import uvicorn
import os
import sys
import subprocess
import signal
import logging
import argparse
import time
import threading
import re
import ray
from contextlib import asynccontextmanager
from typing import Any
from dotenv import load_dotenv
from fastapi import FastAPI

from data_process.ray_config import RayConfig
from utils.logging_utils import configure_logging
from consts.const import (
    REDIS_URL, REDIS_PORT, FLOWER_PORT, RAY_DASHBOARD_PORT, RAY_DASHBOARD_HOST,
    RAY_ACTOR_NUM_CPUS, RAY_NUM_CPUS, DISABLE_RAY_DASHBOARD, DISABLE_CELERY_FLOWER,
    DOCKER_ENVIRONMENT, RAY_OBJECT_STORE_MEMORY_GB, RAY_preallocate_plasma, RAY_TEMP_DIR
)

# Load environment variables
load_dotenv()

# Configure logging with color formatter
configure_logging(logging.INFO)
logging.getLogger("ray").setLevel(logging.WARNING)
logger = logging.getLogger("data_process_service")

# Global variables to track processes
service_processes = {
    'redis': None,
    'ray_cluster': None,
    'workers': [],
    'flower': None,
}

class ServiceManager:
    """Manage all data processing related services"""
    
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.redis_port = config.get('redis_port', REDIS_PORT)
        self.flower_port = config.get('flower_port', FLOWER_PORT)
        self.ray_dashboard_port = config.get('ray_dashboard_port', RAY_DASHBOARD_PORT)
        
        # Unify configuration from command-line arguments and environment variables.
        # A service is disabled if EITHER the command-line flag is set OR the env var is 'true'.
        disable_dashboard_from_args = self.config.get('disable_ray_dashboard', False)
        self.config['disable_ray_dashboard'] = disable_dashboard_from_args or DISABLE_RAY_DASHBOARD

        # Flower is started only if it's enabled by args AND not disabled by env var.
        disable_flower_from_args = self.config.get('disable_celery_flower', False)
        self.config['start_flower'] = not (disable_flower_from_args or DISABLE_CELERY_FLOWER)

        self._shutdown_called = False  # Flag to prevent multiple shutdowns
        self._ray_cluster_started = False  # Track if we started Ray cluster
        
    def start_redis(self):
        """Start Redis server if not already running"""
        # Local Redis is not supported yet
        redis_url = REDIS_URL or f'redis://localhost:{self.redis_port}/0'
        return self._check_redis_connection(redis_url)
    
    def _check_redis_connection(self, redis_url: str) -> bool:
        """Check Redis connection using Python redis client"""
        redis_url = REDIS_URL
        try:
            import redis
            redis_client = redis.from_url(redis_url, socket_timeout=5, socket_connect_timeout=5)
            redis_client.ping()
            logger.info(f"✅ Redis connection successful: {redis_url}")
            return True
        except ImportError:
            logger.error("❌ Redis Python client not available. Please install: pip install redis")
            return False
        except Exception as e:
            logger.error(f"❌ Redis connection failed: {str(e)}")
            return False
    
    def start_ray_cluster(self):
        """Start Ray cluster if not already running"""
        if not self.config.get('start_ray', True):
            logger.info("⏸️ Ray cluster startup disabled")
            return True
            
        try:
            include_dashboard = not self.config.get('disable_ray_dashboard', False)
            # Check if Ray is already initialized
            if ray.is_initialized():
                logger.info("✅ Ray cluster already running")
                return True
            
            # Get Ray configuration from environment
            num_cpus = int(RAY_NUM_CPUS) if RAY_NUM_CPUS else os.cpu_count()
            dashboard_host = RAY_DASHBOARD_HOST
            
            logger.info("🔮 Starting Ray cluster...")
            
            # Initialize Ray using the centralized RayConfig helper
            success = RayConfig.init_ray_for_service(
                num_cpus=num_cpus,
                dashboard_port=self.ray_dashboard_port,
                try_connect_first=True,
                include_dashboard=include_dashboard
            )

            if not success:
                # Fallback to direct Ray initialization
                try:
                    # Set RAY_preallocate_plasma environment variable before initialization
                    os.environ["RAY_preallocate_plasma"] = str(
                        RAY_preallocate_plasma).lower()

                    # Calculate object store memory in bytes
                    object_store_memory = int(
                        RAY_OBJECT_STORE_MEMORY_GB * 1024 * 1024 * 1024)

                    logger.info(
                        f"Fallback: Initializing Ray with object_store_memory={RAY_OBJECT_STORE_MEMORY_GB}GB, preallocate_plasma={RAY_preallocate_plasma}")

                    ray.init(
                        num_cpus=num_cpus,
                        object_store_memory=object_store_memory,
                        _temp_dir=RAY_TEMP_DIR,
                        object_spilling_directory=RAY_TEMP_DIR,
                        include_dashboard=include_dashboard,
                        dashboard_host=dashboard_host,
                        dashboard_port=self.ray_dashboard_port,
                        ignore_reinit_error=True
                    )
                    success = True
                except Exception as e:
                    logger.error(f"Fallback Ray initialization failed: {e}")
                    success = False
            
            if success:
                self._ray_cluster_started = True
                service_processes['ray_cluster'] = True  # Mark as managed by this service
                
                logger.info("✅ Ray cluster initialized successfully!")
                if include_dashboard:
                    logger.info(f"✅ Ray dashboard available at: http://{dashboard_host}:{self.ray_dashboard_port}")
                else:
                    logger.info("⏸️ Ray dashboard disabled")
                
                # Display cluster info
                try:
                    cluster_resources = ray.cluster_resources()
                    logger.info(f"✅ Ray cluster resources: {cluster_resources}")
                except Exception as e:
                    logger.debug(f"❌ Could not get cluster resources: {e}")
                
                # Propagate Ray address to environment for child processes so that
                # subsequently spawned worker processes can connect to the same Ray
                # cluster without additional configuration.
                try:
                    gcs_address = ray.get_runtime_context().gcs_address
                    if gcs_address:
                        os.environ["RAY_ADDRESS"] = gcs_address
                        # Store in config for potential later use
                        self.config['ray_address'] = gcs_address
                        logger.info(f"✅ RAY_ADDRESS environment variable set to {gcs_address}")
                except Exception as e:
                    logger.debug(f"❌ Could not determine Ray address: {e}")
                
                return True
                
        except Exception as e:
            logger.error(f"❌ Error starting Ray cluster: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def start_workers(self):
        """Start Celery workers for process and forward queues"""
        if not self.config.get('start_workers', True):
            logger.info("⏸️ Workers startup disabled")
            return True
            
        try:
            # Check if we're in Docker environment
            logger.info(f"Starting workers in {'Docker' if DOCKER_ENVIRONMENT else 'development'} environment")

            # Dynamically determine concurrency for process-worker based on Ray's CPU resources
            # Each process task requires 1 CPU from Ray. Concurrency should not exceed available CPUs.
            # Fallback to 1 if os.cpu_count() is None.
            total_cpus = int(RAY_NUM_CPUS) if RAY_NUM_CPUS else (os.cpu_count() or 1)

            # Get the number of CPUs requested by each actor.
            ray_actor_num_cpus = RAY_ACTOR_NUM_CPUS
            
            # Calculate concurrency for the process-worker. Each worker will spawn an actor,
            # so we limit concurrency to avoid oversubscribing Ray's CPU resources.
            process_worker_concurrency = max(1, total_cpus // ray_actor_num_cpus)
            
            # For forward-worker, it's I/O bound. A higher concurrency is fine, but we can cap it
            # relative to CPU count to avoid creating excessive threads on small machines.
            forward_worker_concurrency = min(8, total_cpus * 2)

            logger.debug(f"Total available CPUs: {total_cpus}")
            logger.debug(f"CPUs per processing actor (RAY_ACTOR_NUM_CPUS): {ray_actor_num_cpus}")
            logger.debug(f"Process-worker concurrency set to: {process_worker_concurrency}")
            logger.debug(f"Forward-worker concurrency set to: {forward_worker_concurrency}")

            # Define worker configurations based on split architecture:
            # - process-worker handles orchestration (process_q)
            # - process-part-worker handles split sub-tasks (process_part_q)
            # - forward-worker handles vectorization/storage (forward_q)
            workers_config = [
                {
                    'name': 'process-worker',
                    'queue': 'process_q',
                    'concurrency': process_worker_concurrency
                },
                {
                    'name': 'process-part-worker',
                    'queue': 'process_part_q',
                    'concurrency': process_worker_concurrency
                },
                {
                    'name': 'forward-worker', 
                    'queue': 'forward_q',
                    'concurrency': forward_worker_concurrency
                }
            ]
            
            # Start each worker in a separate process
            for config in workers_config:
                # Use full Python path and correct module path
                worker_cmd = [
                    sys.executable, '-c',
                    f'''
import sys, os, logging

# The CWD for subprocess.Popen is already set to the 'backend' directory.
# PYTHONPATH is also set to the 'backend' directory by the parent process.
# So, modules within 'data_process' should be directly importable.

# Ensure the current working directory (backend) is in path for relative imports if any.
# Also ensure the parent of CWD (project root) is in path for nexent.* imports
project_root = os.path.dirname(os.getcwd())
if os.getcwd() not in sys.path:
    sys.path.insert(0, os.getcwd())
if project_root not in sys.path:
    sys.path.insert(0, project_root)

logging.basicConfig(level=logging.INFO, format='[%(asctime)s: %(levelname)s/%(name)s] %(message)s')
logger = logging.getLogger("data_process.worker_launcher")

os.environ["QUEUES"] = "{config['queue']}"  # backward compatibility
os.environ["WORKER_NAME"] = "{config['name']}"
os.environ["WORKER_CONCURRENCY"] = "{config['concurrency']}"

try:
    # Ensure the Celery app is discovered correctly
    from data_process.app import app as celery_app
    
    logger.debug(f"Celery app instance: {{celery_app}}")
    logger.debug(f"Attempting to start worker for queue: {config['queue']}")
    from data_process.worker import start_worker
    # Re-apply launcher values after imports in case .env override changed them.
    os.environ["QUEUES"] = "{config['queue']}"
    os.environ["WORKER_NAME"] = "{config['name']}"
    os.environ["WORKER_CONCURRENCY"] = "{config['concurrency']}"
    start_worker()
except ImportError as e:
    logger.error(f"Import error: {{e}}")
    logger.error(f"Python path: {{sys.path}}")
    logger.error(f"Current directory: {{os.getcwd()}}")
    sys.exit(1)
except Exception as e_exec:
    logger.error(f"Error executing worker: {{e_exec}}")
    import traceback
    logger.error(traceback.format_exc())
    sys.exit(1)
                    '''  # noqa: F821
                ]

                logger.info(f"Starting {config['name']} worker for queue: {config['queue']} with concurrency: {config['concurrency']}")

                # Get the backend directory path to ensure correct module import
                # This should resolve to the 'backend' directory where this service script is located.
                backend_dir = os.path.dirname(os.path.abspath(__file__))
                if not os.path.isdir(os.path.join(backend_dir, "data_process")) :
                     # if this service script itself is not in backend, but one level up
                     possible_backend_dir = os.path.join(backend_dir, "backend")
                     if os.path.isdir(os.path.join(possible_backend_dir, "data_process")):
                         backend_dir = possible_backend_dir


                # Set environment variables for the worker process
                worker_env = os.environ.copy()
                # Ensure REDIS_URL is correctly passed from the parent environment
                if REDIS_URL: # Make sure it is set
                    worker_env['REDIS_URL'] = REDIS_URL
                else: # Default if not set. This should match your Celery app config.
                     worker_env['REDIS_URL'] = f'redis://localhost:{self.redis_port}/0'

                # Allow running as root in containerized environments
                worker_env['C_FORCE_ROOT'] = '1'

                # PYTHONPATH should point to the project root to allow nexent.data_process
                # and also backend to allow data_process.*
                project_root_dir = os.path.dirname(backend_dir)
                python_path_entries = [project_root_dir, backend_dir]
                existing_python_path = worker_env.get('PYTHONPATH')
                if existing_python_path:
                    python_path_entries.extend(existing_python_path.split(os.pathsep))
                worker_env['PYTHONPATH'] = os.pathsep.join(list(dict.fromkeys(python_path_entries))) # Unique entries

                logger.info(f"Worker CWD: {backend_dir}")
                logger.info(f"Worker PYTHONPATH: {worker_env['PYTHONPATH']}")

                # Start the worker process with real-time output
                process = subprocess.Popen(
                    worker_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True,
                    cwd=backend_dir,  # Run from backend directory for module import
                    env=worker_env  # Pass environment variables
                )
                
                service_processes['workers'].append({
                    'process': process,
                    'name': config['name'],
                    'queue': config['queue']
                })
                
                logger.info(f"Started {config['name']} worker with PID: {process.pid}")
                
                # Start a thread to capture and log worker output
                def log_worker_output(process, worker_name):
                    log_mapping = {
                        'INFO': logging.INFO,
                        'WARNING': logging.WARNING,
                        'ERROR': logging.ERROR,
                        'DEBUG': logging.DEBUG,
                        'CRITICAL': logging.CRITICAL
                    }
                    # Regex to capture log level and message from Celery-style logs
                    log_pattern = re.compile(r'^\[[^\]]+:\s*(?P<level>\w+)/[^\]]+\]\s*(?P<message>.*)$')

                    try:
                        for line in iter(process.stdout.readline, ''):
                            line = line.strip()
                            if not line:
                                continue

                            match = log_pattern.match(line)
                            if match:
                                level_name = match.group('level').upper()
                                message = match.group('message')
                                log_level = log_mapping.get(level_name, logging.INFO)

                                # Only log meaningful messages
                                if message and 'imported' not in message and 'Creating pool' not in message:
                                    logger.log(log_level, f"[{worker_name}] {message}")
                            elif 'celery@' not in line: # Filter out celery startup noise
                                logger.info(f"[{worker_name}] {line}")
                    except Exception as e:
                        logger.warning(f"Error in log thread for worker {worker_name}: {str(e)}")
                    finally:
                        logger.debug(f"Log thread for worker {worker_name} has terminated")
                
                output_thread = threading.Thread(
                    target=log_worker_output, 
                    args=(process, config['name']),
                    daemon=True
                )
                output_thread.start()
            
            logger.info("✅ All Celery workers started successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error starting workers: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def start_flower(self):
        """Start Flower monitoring for Celery"""
        try:
            # Get Redis URL from environment to ensure consistency
            redis_url = REDIS_URL
            
            # Get the backend directory path to ensure correct module import
            backend_dir = os.path.dirname(os.path.abspath(__file__))
            
            # Set up environment variables for Flower configuration
            flower_env = os.environ.copy()
            flower_env.update({
                'FLOWER_PORT': str(self.flower_port),
                'FLOWER_BROKER_API': redis_url,
                'FLOWER_BASIC_AUTH': 'admin:admin',
                'FLOWER_PERSISTENT': 'True',
                'FLOWER_DB': 'flower_db.sqlite',
                'FLOWER_AUTO_REFRESH': 'True',
                'FLOWER_MAX_WORKERS': '5000',
                'FLOWER_MAX_TASKS': '10000',
                # Add environment variables to help isolate Flower from Ray issues
                'RAY_DISABLE_IMPORT_WARNING': '1',
                'RAY_DEDUP_LOGS': '0',
                'CELERY_CONFIG_MODULE': 'data_process.app'
            })
            
            # Ensure PYTHONPATH includes the project root for proper module imports
            project_root_dir = os.path.dirname(backend_dir)
            python_path_entries = [project_root_dir, backend_dir]
            existing_python_path = flower_env.get('PYTHONPATH')
            if existing_python_path:
                python_path_entries.extend(existing_python_path.split(os.pathsep))
            flower_env['PYTHONPATH'] = os.pathsep.join(list(dict.fromkeys(python_path_entries)))
            
            # Use Flower command with proper app specification
            # Try different command formats for compatibility
            flower_cmd = [
                sys.executable, '-m', 'celery',
                '-A', 'data_process.app:app', 'flower',
                '--port=' + str(self.flower_port),
                '--broker-api=' + redis_url,
                '--basic-auth=admin:admin',
                '--auto-refresh=True',
                '--max-workers=5000',
                '--max-tasks=10000'
            ]
            
            logger.debug(f"Flower command: {' '.join(flower_cmd)}")
            logger.debug(f"Flower CWD: {backend_dir}")
            logger.debug(f"Flower PYTHONPATH: {flower_env['PYTHONPATH']}")
            logger.debug(f"Flower REDIS_URL: {redis_url}")
            
            # Platform-specific arguments for creating a new process group/session
            # This allows us to terminate the entire process tree reliably.
            popen_kwargs = {}
            if sys.platform == "win32":
                popen_kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                # Use os.setsid to create a new session, making the process group leader.
                # This is the standard way on Unix-like systems.
                popen_kwargs['preexec_fn'] = os.setsid

            process = subprocess.Popen(
                flower_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=backend_dir,  # Run from backend directory for module import
                env=flower_env,  # Pass environment variables for configuration
                **popen_kwargs
            )
            
            service_processes['flower'] = process
            logger.info(f"✅ Flower monitoring started with PID: {process.pid}")
            
            # Start thread to log Flower output
            def log_flower_output():
                log_mapping = {
                    'INFO': logging.INFO,
                    'WARNING': logging.WARNING,
                    'ERROR': logging.ERROR,
                    'DEBUG': logging.DEBUG,
                    'CRITICAL': logging.CRITICAL
                }
                # Regex for Flower logs (e.g., [I 240...], or ... INFO - ...)
                flower_pattern1 = re.compile(r'\[([IWEFDC])\s\d{6}\s\d{2}:\d{2}:\d{2}\s[^\]]+\]\s*(.*)')
                flower_pattern2 = re.compile(r'^\S+\s*-\s*(INFO|WARNING|ERROR|DEBUG|CRITICAL)\s*-\s*(.*)')
                level_map_short = {'I': 'INFO', 'W': 'WARNING', 'E': 'ERROR', 'D': 'DEBUG', 'C': 'CRITICAL'}

                try:
                    if process.stdout:
                        for line in iter(process.stdout.readline, ''):
                            clean_line = line.strip()
                            if not clean_line:
                                continue
                            
                            level_name, message = None, None
                            match1 = flower_pattern1.match(clean_line)
                            match2 = flower_pattern2.match(clean_line)

                            if match1:
                                level_char = match1.group(1)
                                level_name = level_map_short.get(level_char)
                                message = match1.group(2)
                            elif match2:
                                level_name = match2.group(1).upper()
                                message = match2.group(2)
                            
                            if level_name and message:
                                log_level = log_mapping.get(level_name, logging.INFO)
                                # Filter out Ray-related error messages from Flower logs
                                if 'ray' not in message.lower() or 'started' in message.lower():
                                    logger.log(log_level, f"[Flower] {message}")
                            elif 'ray' not in clean_line.lower() or 'started' in clean_line.lower():
                                logger.info(f"[Flower] {clean_line}")

                except Exception as e:
                    logger.warning(f"❌ Error in Flower log thread: {str(e)}")
                finally:
                    logger.debug("🛑 Flower log thread has terminated")
            
            output_thread = threading.Thread(target=log_flower_output, daemon=True)
            output_thread.start()
            
            # Wait a moment to check if Flower actually started
            time.sleep(3)
            
            # Check if process is still running
            if process.poll() is not None:
                logger.error(f"❌ Flower process exited with return code {process.returncode}")
                try:
                    if process.stdout:
                        output = process.stdout.read()
                        if output:
                            logger.error(f"❌ Flower error output: {output}")
                except Exception as _:
                    pass
                return False
            
            return True
            
        except FileNotFoundError:
            logger.error("❌ Flower not found. Please install: pip install flower")
            logger.error("   Note: Use 'python -m flower' instead of 'flower' command")
            return False
        except Exception as e:
            logger.error(f"❌ Error starting Flower: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def start_all_services(self):
        """Start all configured services"""
        logger.info("🚀 Starting Data Processing Services")
        logger.info("=" * 50)
        
        # Start services in specific order for proper dependencies
        services = [
            ("Redis", self.start_redis, 'start_redis'),
            ("Ray Cluster", self.start_ray_cluster, 'start_ray'),
            ("Celery Workers", self.start_workers, 'start_workers'),
            ("Flower Monitoring", self.start_flower, 'start_flower')
        ]
        
        success_count = 0
        enabled_count = 0

        logger.info(f"📋 Effective service config: {self.config}")
        
        for service_name, start_func, config_key in services:
            if self.config.get(config_key, True):
                enabled_count += 1
                logger.info(f"Starting {service_name}...")
                if start_func():
                    success_count += 1
                    
                    # Add delay after starting workers to allow registration
                    if service_name == "Celery Workers":
                        logger.info("Waiting for workers to register...")
                        time.sleep(5)  # Give workers time to connect and register
                    
                else:
                    logger.warning(f"Failed to start {service_name}")
            else:
                logger.info(f"⏸️ {service_name} disabled")
        
        logger.info("=" * 50)
        logger.info(f"✅ Started {success_count}/{enabled_count} services successfully")
        
        if success_count > 0:
            self.log_service_info()

        # Start auto-summary scheduler
        from services.auto_summary_scheduler import auto_summary_scheduler
        auto_summary_scheduler.start()

        return success_count == enabled_count
    
    def log_service_info(self):
        """Print information about running services"""
        logger.info("\n📋 Service Information:")
        logger.info("-" * 30)
        
        logger.info(f"🔴 Redis: {REDIS_URL}")
        
        if self.config.get('start_ray', True):
            if ray.is_initialized():
                try:
                    gcs_address = ray.get_runtime_context().gcs_address
                    logger.info(f"🔮 Ray Cluster: {gcs_address}")
                    if not self.config.get('disable_ray_dashboard', False):
                        logger.info(f"🎯 Ray Dashboard: http://localhost:{self.ray_dashboard_port}")
                except Exception as _:
                    logger.info("🔮 Ray Cluster: Running locally")
            else:
                logger.info("❌ Ray Cluster: Not started")
        
        if self.config.get('start_workers', True):
            logger.info(f"👷 Workers: {len(service_processes['workers'])} processes")
            for worker in service_processes['workers']:
                logger.info(f"   - {worker['name']}: queue={worker['queue']}")
        
        if self.config.get('start_flower', True):
            logger.info(f"🌸 Flower: http://localhost:{self.flower_port}")
        
        logger.info("-" * 30)
    
    def stop_all_services(self):
        """Stop all running services"""
        if self._shutdown_called:
            return
        
        self._shutdown_called = True
        
        logger.info("🛑 Stopping all services...")
        
        # Stop workers first to ensure clean shutdown
        if service_processes['workers']:
            logger.info("Stopping Celery workers...")
            for worker_info in service_processes['workers']:
                process = worker_info['process']
                name = worker_info['name']
                
                try:
                    if process.poll() is None:
                        logger.info(f"Terminating {name} worker (PID: {process.pid})")
                        process.terminate()
                        
                        try:
                            process.wait(timeout=10)
                            logger.info(f"{name} worker terminated gracefully")
                        except subprocess.TimeoutExpired:
                            logger.warning(f"{name} worker didn't terminate gracefully, killing it")
                            process.kill()
                            process.wait()
                    else:
                        logger.info(f"{name} worker already terminated")
                        
                except Exception as e:
                    logger.error(f"Error stopping {name} worker: {str(e)}")
            
            service_processes['workers'].clear()
            logger.info("All workers stopped")
        
        # Stop Ray cluster BEFORE stopping Flower to avoid shutdown conflicts
        if self._ray_cluster_started and ray.is_initialized():
            try:
                logger.info("🛑 Stopping Ray cluster...")
                ray.shutdown()
                self._ray_cluster_started = False
                service_processes['ray_cluster'] = None
                logger.info("🛑 Ray cluster stopped")
                # Give some time for Ray to fully shutdown
                time.sleep(1)
            except Exception as e:
                logger.error(f"❌ Error stopping Ray cluster: {str(e)}")
        
        # Stop Flower after Ray is shutdown to prevent conflicts
        if service_processes['flower']:
            process = service_processes['flower']
            pid = process.pid
            logger.info(f"🛑 Stopping Flower monitoring (PID: {pid})...")

            try:
                if process.poll() is None:  # Check if process is still running
                    if sys.platform == "win32":
                        # On Windows, send CTRL_BREAK_EVENT to the process group.
                        logger.info(f"Sending CTRL_BREAK_EVENT to Flower process group (PID: {pid}) on Windows.")
                        process.send_signal(signal.CTRL_BREAK_EVENT)
                    else:
                        # On Unix-like systems, send SIGTERM to the entire process group.
                        logger.info(f"Sending SIGTERM to Flower process group (PGID: {os.getpgid(pid)}).")
                        os.killpg(os.getpgid(pid), signal.SIGTERM)

                    # Wait for the process to terminate
                    try:
                        process.wait(timeout=10)
                        logger.info("✅ Flower stopped gracefully.")
                    except subprocess.TimeoutExpired:
                        logger.warning("Flower did not terminate gracefully after 10s. Forcing kill.")
                        if sys.platform == "win32":
                            # Use taskkill as a more forceful method to ensure the process tree is killed.
                            logger.info(f"Using taskkill to forcefully terminate Flower process tree (PID: {pid}).")
                            subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)], check=False, capture_output=True)
                        else:
                            # Send SIGKILL to the process group as a last resort.
                            logger.info(f"Sending SIGKILL to Flower process group (PGID: {os.getpgid(pid)}).")
                            os.killpg(os.getpgid(pid), signal.SIGKILL)
                        
                        process.wait(timeout=5) # Final wait
                        logger.info("✅ Flower process forcefully terminated.")
                else:
                    logger.info("✅ Flower process was already terminated.")
            
            except (ProcessLookupError, OSError) as e:
                logger.warning(f"Could not terminate Flower process group, it may have already exited: {e}")
                # Fallback to killing just the main process if it's still running
                if process.poll() is None:
                    process.kill()
                    logger.info("Fell back to killing only the main Flower process.")
            except Exception as e:
                logger.error(f"An unexpected error occurred while stopping Flower: {str(e)}")
                # Best-effort kill as a final fallback
                if process.poll() is None:
                    try:
                        process.kill()
                        logger.warning("Flower process was force-killed due to an error during shutdown.")
                    except Exception as final_e:
                        logger.error(f"Final attempt to kill Flower process failed: {final_e}")
            finally:
                service_processes['flower'] = None

        # Stop auto-summary scheduler
        from services.auto_summary_scheduler import auto_summary_scheduler
        auto_summary_scheduler.stop()

        # Stop Redis last
        if service_processes['redis']:
            try:
                logger.info("Stopping Redis server...")
                service_processes['redis'].terminate()
                service_processes['redis'].wait(timeout=5)
                logger.info("Redis stopped")
            except Exception as _:
                service_processes['redis'].kill()
                logger.info("Redis force killed")
            service_processes['redis'] = None
        
        logger.info("✅ All services stopped")

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Data Processing Service with integrated Redis, Workers, and Monitoring",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python data_process_service.py                           # Start all services (Redis, Ray, Workers, Flower)
  python data_process_service.py --disable-celery-flower   # Skip Flower monitoring
  python data_process_service.py --disable-ray-dashboard   # Skip Ray dashboard
  python data_process_service.py --no-ray                  # Skip Ray cluster (use external Ray)
  python data_process_service.py --ray-dashboard-port 8266 # Use custom Ray dashboard port
        """
    )
    
    # Service control arguments
    parser.add_argument('--no-workers', action='store_true',
                       help='Do not start Celery workers')
    parser.add_argument('--no-ray', action='store_true',
                       help='Do not start Ray cluster')
    
    # Port configuration
    parser.add_argument('--redis-port', type=int, default=REDIS_PORT,
                       help='Redis server port (default: env REDIS_PORT or 6379)')
    parser.add_argument('--flower-port', type=int, default=FLOWER_PORT,
                       help='Flower monitoring port (default: env FLOWER_PORT or 5555)')
    parser.add_argument('--ray-dashboard-port', type=int, default=RAY_DASHBOARD_PORT,
                       help='Ray dashboard port (default: env RAY_DASHBOARD_PORT or 8265)')
    
    # Dashboard / monitoring disable flags
    parser.add_argument('--disable-ray-dashboard', action='store_true',
                       help='Disable Ray dashboard if this flag is present.')
    parser.add_argument('--disable-celery-flower', action='store_true',
                       help='Disable Celery Flower monitoring if this flag is present.')
    
    # API server configuration
    parser.add_argument('--api-host', default='0.0.0.0',
                       help='API server host (default: 0.0.0.0)')
    parser.add_argument('--api-port', type=int, default=5012,
                       help='API server port (default: 5012)')
    
    return parser.parse_args()

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    
    # Prevent multiple signal handling
    if 'service_manager' in globals() and service_manager and not service_manager._shutdown_called:
        try:
            service_manager.stop_all_services()
            logger.info("Graceful shutdown completed")
        except Exception as e:
            logger.error(f"Error during shutdown: {str(e)}")
            # Force exit if graceful shutdown fails
            logger.info("Forcing exit due to shutdown error")
            os._exit(1)
    
    sys.exit(0)

# Register signal handlers for graceful shutdown
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

# Global service manager for cleanup
service_manager = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan event handler for startup and shutdown"""
    global service_manager
    
    # Startup
    logger.info("Starting data processing service...")
    
    yield
    
    # Shutdown
    logger.info("Shutting down data processing service...")
    if service_manager and not service_manager._shutdown_called:
        service_manager.stop_all_services()
    logger.info("Data processing service shutdown complete")

def create_app():
    """Create FastAPI application"""
    # Lazy import router to avoid overhead during module initialization
    from apps.data_process_app import router as data_process_router
    
    app = FastAPI(root_path="/api", lifespan=lifespan)
    app.include_router(data_process_router)
    return app

def main():
    """Main entry point"""
    global service_manager
    
    # Parse command line arguments
    args = parse_arguments()
    
    # Create service configuration
    config = {
        'start_workers': not args.no_workers,
        'start_flower': not args.disable_celery_flower,
        'start_ray': not args.no_ray,
        'disable_ray_dashboard': args.disable_ray_dashboard,
        'redis_port': args.redis_port,
        'flower_port': args.flower_port,
        'ray_dashboard_port': args.ray_dashboard_port,
    }
    
    # Create service manager
    service_manager = ServiceManager(config)
    
    # Note: Using lifespan and signal handlers for cleanup instead of atexit
    # to avoid multiple cleanup calls
    
    try:
        # Start all configured services
        service_manager.start_all_services()
        
        # Create and start FastAPI app
        app = create_app()
        
        logger.info(f"🌐 Starting API server on {args.api_host}:{args.api_port}")
        uvicorn.run(
            app, 
            host=args.api_host,
            port=args.api_port,
            log_level="warning"
        )
        
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Error starting service: {str(e)}")
        sys.exit(1)
    finally:
        if service_manager and not service_manager._shutdown_called:
            service_manager.stop_all_services()

if __name__ == "__main__":
    main()

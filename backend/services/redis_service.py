import json
import logging
from typing import Dict, Any

import redis

from consts.const import REDIS_URL, REDIS_BACKEND_URL

logger = logging.getLogger(__name__)


class RedisService:
    """Redis service for managing cache and task data"""

    def __init__(self):
        self._client = None
        self._backend_client = None

    @property
    def client(self) -> redis.Redis:
        """Get Redis client for general use"""
        if self._client is None:
            if not REDIS_URL:
                raise ValueError("REDIS_URL environment variable is not set")
            self._client = redis.from_url(REDIS_URL, socket_timeout=5, socket_connect_timeout=5)
        return self._client

    @property
    def backend_client(self) -> redis.Redis:
        """Get Redis client for backend use (Celery task results)"""
        if self._backend_client is None:
            redis_backend_url = REDIS_BACKEND_URL or REDIS_URL
            if not redis_backend_url:
                raise ValueError("REDIS_BACKEND_URL or REDIS_URL environment variable is not set")
            self._backend_client = redis.from_url(redis_backend_url, socket_timeout=5, socket_connect_timeout=5)
        return self._backend_client

    def delete_knowledgebase_records(self, index_name: str) -> Dict[str, Any]:
        """
        Delete all Redis records related to a specific knowledge base

        Args:
            index_name: Name of the knowledge base (index) to clean up

        Returns:
            Dict containing cleanup results
        """
        logger.info(f"Starting Redis cleanup for knowledge base: {index_name}")

        result = {
            "index_name": index_name,
            "celery_tasks_deleted": 0,
            "cache_keys_deleted": 0,
            "total_deleted": 0,
            "errors": []
        }

        try:
            # 1. Clean up Celery task results related to this knowledge base
            celery_deleted = self._cleanup_celery_tasks(index_name)
            result["celery_tasks_deleted"] = celery_deleted

            # 2. Clean up any cache keys related to this knowledge base
            cache_deleted = self._cleanup_cache_keys(index_name)
            result["cache_keys_deleted"] = cache_deleted

            result["total_deleted"] = celery_deleted + cache_deleted

            logger.info(f"Redis cleanup completed for {index_name}: "
                       f"Celery tasks: {celery_deleted}, Cache keys: {cache_deleted}")

        except Exception as e:
            error_msg = f"Error during Redis cleanup for {index_name}: {str(e)}"
            logger.error(error_msg)
            result["errors"].append(error_msg)

        return result

    def delete_document_records(self, index_name: str, path_or_url: str) -> Dict[str, Any]:
        """
        Delete Redis records related to a specific document in a knowledge base

        Args:
            index_name: Name of the knowledge base (index)
            path_or_url: Path or URL of the document to clean up

        Returns:
            Dict containing cleanup results
        """
        logger.info(f"Starting Redis cleanup for document: {path_or_url} in knowledge base: {index_name}")

        result = {
            "index_name": index_name,
            "document_path": path_or_url,
            "celery_tasks_deleted": 0,
            "cache_keys_deleted": 0,
            "total_deleted": 0,
            "errors": []
        }

        try:
            # 1. Clean up Celery task results related to this specific document
            celery_deleted = self._cleanup_document_celery_tasks(index_name, path_or_url)
            result["celery_tasks_deleted"] = celery_deleted

            # 2. Clean up any cache keys related to this specific document
            cache_deleted = self._cleanup_document_cache_keys(index_name, path_or_url)
            result["cache_keys_deleted"] = cache_deleted

            result["total_deleted"] = celery_deleted + cache_deleted

            logger.info(f"Redis cleanup completed for document {path_or_url} in {index_name}: "
                       f"Celery tasks: {celery_deleted}, Cache keys: {cache_deleted}")

        except Exception as e:
            error_msg = f"Error during Redis cleanup for document {path_or_url}: {str(e)}"
            logger.error(error_msg)
            result["errors"].append(error_msg)

        return result

    def _recursively_delete_task_and_parents(self, task_id: str) -> tuple[int, set]:
        """
        Iteratively delete a Celery task and all its parent tasks from Redis.
        A single task chain is deleted, and the IDs of the deleted tasks are returned.

        Args:
            task_id: The starting task ID.

        Returns:
            A tuple containing:
            - int: The number of deleted task records.
            - set: A set of processed task IDs in the chain.
        """
        deleted_count = 0
        processed_ids = set()
        current_task_id = task_id

        while current_task_id:
            if current_task_id in processed_ids:
                logger.warning(f"Detected a cycle or repeated task in parent chain, breaking at: {current_task_id}")
                break

            processed_ids.add(current_task_id)
            task_key = f'celery-task-meta-{current_task_id}'

            try:
                task_data = self.backend_client.get(task_key)

                parent_id = None
                if task_data:
                    # Get parent_id before deleting
                    try:
                        task_info = json.loads(task_data)
                        parent_id = task_info.get('parent_id')
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.warning(f"Failed to parse task data for {task_key}, cannot find parent: {e}")
                        parent_id = None

                    # Delete the current task
                    if self.backend_client.delete(task_key):
                        deleted_count += 1
                        logger.debug(f"Deleted task record from chain: {task_key}")

                current_task_id = parent_id

            except Exception as e:
                logger.error(f"Error while processing task {task_key} in recursive delete: {e}")
                # Stop if any redis error occurs
                break

        return deleted_count, processed_ids

    def _cleanup_celery_tasks(self, index_name: str) -> int:
        """
        Clean up Celery task results related to the knowledge base and their parents.

        Args:
            index_name: Name of the knowledge base

        Returns:
            Number of task records deleted
        """
        total_deleted_count = 0
        processed_tasks = set()  # Track tasks that have been processed to avoid redundant work

        try:
            # Get all Celery task result keys
            task_keys = self.backend_client.keys('celery-task-meta-*')

            for key in task_keys:
                try:
                    # Get task data
                    task_data = self.backend_client.get(key)
                    if task_data:
                        import json
                        task_info = json.loads(task_data)

                        # Check if this task is related to our knowledge base
                        result = task_info.get('result', {})
                        task_index_name = None

                        if isinstance(result, dict):
                            # Standard check for successful tasks
                            task_index_name = (
                                result.get('index_name') or
                                task_info.get('index_name') or
                                result.get('kwargs', {}).get('index_name')
                            )

                            # Check for failed tasks where metadata is in the exception message
                            if task_index_name is None and 'exc_message' in result:
                                try:
                                    exc_str = str(result['exc_message'])
                                    if '{' in exc_str and '}' in exc_str:
                                        json_part = exc_str[exc_str.find('{'):exc_str.rfind('}')+1]
                                        cleaned_json_part = json_part.replace('\\"', '"')
                                        error_data = json.loads(cleaned_json_part)
                                        task_index_name = error_data.get('index_name')
                                except (json.JSONDecodeError, TypeError, IndexError) as e:
                                    key_str = key.decode('utf-8') if isinstance(key, bytes) else key
                                    logger.warning(f"Could not parse exception metadata for task key {key_str}: {e}")

                        if task_index_name == index_name:
                            key_str = key.decode('utf-8') if isinstance(key, bytes) else key
                            task_id = key_str.replace('celery-task-meta-', '')
                            if task_id not in processed_tasks:
                                deleted, processed_chain = self._recursively_delete_task_and_parents(task_id)
                                total_deleted_count += deleted
                                processed_tasks.update(processed_chain)

                except Exception as e:
                    logger.warning(f"Error processing task key {key} for cleanup: {str(e)}")
                    continue

        except Exception as e:
            logger.error(f"Error cleaning up Celery tasks: {str(e)}")
            raise

        return total_deleted_count

    def _cleanup_cache_keys(self, index_name: str) -> int:
        """
        Clean up cache keys related to the knowledge base

        Args:
            index_name: Name of the knowledge base

        Returns:
            Number of cache keys deleted
        """
        deleted_count = 0

        try:
            # Define patterns to search for cache keys related to the knowledge base
            patterns = [
                f"*{index_name}*",  # Any key containing the index name
                f"kb:{index_name}:*",  # Knowledge base specific cache keys
                f"index:{index_name}:*",  # Index specific cache keys
                f"search:{index_name}:*",  # Search cache keys
            ]

            for pattern in patterns:
                try:
                    keys = self.client.keys(pattern)
                    if keys:
                        # Delete keys in batch for efficiency
                        deleted = self.client.delete(*keys)
                        deleted_count += deleted
                        logger.debug(f"Deleted {deleted} cache keys matching pattern: {pattern}")

                except Exception as e:
                    logger.warning(f"Error processing cache pattern {pattern}: {str(e)}")
                    continue

        except Exception as e:
            logger.error(f"Error cleaning up cache keys: {str(e)}")
            raise

        return deleted_count

    def _cleanup_document_celery_tasks(self, index_name: str, path_or_url: str) -> int:
        """
        Clean up Celery task results related to a specific document and their parents.

        Args:
            index_name: Name of the knowledge base
            path_or_url: Path or URL of the document

        Returns:
            Number of task records deleted
        """
        total_deleted_count = 0
        processed_tasks = set()

        try:
            # Get all Celery task result keys
            task_keys = self.backend_client.keys('celery-task-meta-*')

            for key in task_keys:
                key_str = key.decode('utf-8') if isinstance(key, bytes) else key
                task_id = key_str.replace('celery-task-meta-', '')

                if task_id in processed_tasks:
                    continue

                try:
                    # Get task data
                    task_data = self.backend_client.get(key)
                    if task_data:
                        import json
                        task_info = json.loads(task_data)

                        # Check if this task is related to our specific document
                        result = task_info.get('result', {})
                        task_index_name = None
                        task_source = None

                        if isinstance(result, dict):
                            # Standard check for successful tasks
                            task_index_name = (
                                result.get('index_name') or
                                task_info.get('index_name') or
                                result.get('kwargs', {}).get('index_name')
                            )

                            task_source = (
                                result.get('source') or
                                result.get('path_or_url') or
                                task_info.get('source') or
                                task_info.get('path_or_url') or
                                result.get('kwargs', {}).get('source') or
                                result.get('kwargs', {}).get('path_or_url')
                            )

                            # Check for failed tasks where metadata is in the exception message
                            if task_index_name is None and 'exc_message' in result:
                                try:
                                    exc_str = str(result['exc_message'])
                                    if '{' in exc_str and '}' in exc_str:
                                        json_part = exc_str[exc_str.find('{'):exc_str.rfind('}')+1]
                                        cleaned_json_part = json_part.replace('\\"', '"')
                                        error_data = json.loads(cleaned_json_part)
                                        task_index_name = error_data.get('index_name')
                                        task_source = error_data.get('source') or error_data.get('path_or_url')
                                except (json.JSONDecodeError, TypeError, IndexError) as e:
                                    logger.warning(f"Could not parse exception metadata for task {task_id}: {e}")

                        # Match both index name and document path/source
                        if task_index_name == index_name and task_source == path_or_url:
                            # Recursively delete this task and its parents
                            if task_id not in processed_tasks:
                                deleted, processed_chain = self._recursively_delete_task_and_parents(task_id)
                                total_deleted_count += deleted
                                processed_tasks.update(processed_chain)

                except Exception as e:
                    logger.warning(f"Error processing task key {key} for document cleanup: {str(e)}")
                    continue

        except Exception as e:
            logger.error(f"Error cleaning up document Celery tasks: {str(e)}")
            raise

        return total_deleted_count

    def _cleanup_document_cache_keys(self, index_name: str, path_or_url: str) -> int:
        """
        Clean up cache keys related to a specific document

        Args:
            index_name: Name of the knowledge base
            path_or_url: Path or URL of the document

        Returns:
            Number of cache keys deleted
        """
        deleted_count = 0

        try:
            # Create a safe identifier from the path_or_url for cache key matching
            import hashlib
            import urllib.parse

            # Create different possible cache key patterns for the document
            safe_path = urllib.parse.quote(path_or_url, safe='')
            path_hash = hashlib.md5(path_or_url.encode()).hexdigest()

            # Define patterns to search for cache keys related to the specific document
            patterns = [
                f"*{index_name}*{safe_path}*",  # Cache keys containing both index name and safe path
                f"*{index_name}*{path_hash}*",  # Cache keys containing both index name and path hash
                f"kb:{index_name}:doc:{safe_path}*",  # Document specific cache keys
                f"kb:{index_name}:doc:{path_hash}*",  # Document specific cache keys with hash
                f"doc:{safe_path}:*",  # Document specific cache
                f"doc:{path_hash}:*",  # Document specific cache with hash
            ]

            for pattern in patterns:
                try:
                    keys = self.client.keys(pattern)
                    if keys:
                        # Delete keys in batch for efficiency
                        deleted = self.client.delete(*keys)
                        deleted_count += deleted
                        logger.debug(f"Deleted {deleted} document cache keys matching pattern: {pattern}")

                except Exception as e:
                    logger.warning(f"Error processing document cache pattern {pattern}: {str(e)}")
                    continue

        except Exception as e:
            logger.error(f"Error cleaning up document cache keys: {str(e)}")
            raise

        return deleted_count

    def get_knowledgebase_task_count(self, index_name: str) -> int:
        """
        Get the count of Redis records related to a knowledge base

        Args:
            index_name: Name of the knowledge base

        Returns:
            Number of records found
        """
        count = 0

        try:
            # Count Celery tasks
            task_keys = self.backend_client.keys('celery-task-meta-*')
            for key in task_keys:
                try:
                    task_data = self.backend_client.get(key)
                    if task_data:
                        import json
                        task_info = json.loads(task_data)
                        result = task_info.get('result', {})
                        if isinstance(result, dict):
                            task_index_name = (
                                result.get('index_name') or
                                task_info.get('index_name') or
                                result.get('kwargs', {}).get('index_name')
                            )
                            if task_index_name == index_name:
                                count += 1
                except Exception:
                    continue

            # Count cache keys
            patterns = [f"*{index_name}*", f"kb:{index_name}:*", f"index:{index_name}:*"]
            for pattern in patterns:
                try:
                    keys = self.client.keys(pattern)
                    count += len(keys)
                except Exception:
                    continue

        except Exception as e:
            logger.error(f"Error counting knowledge base records: {str(e)}")

        return count

    def ping(self) -> bool:
        """Test Redis connection"""
        try:
            self.client.ping()
            self.backend_client.ping()
            return True
        except Exception as e:
            logger.error(f"Redis ping failed: {str(e)}")
            return False


# Global Redis service instance
_redis_service = None


def get_redis_service() -> RedisService:
    """Get the global Redis service instance"""
    global _redis_service
    if _redis_service is None:
        _redis_service = RedisService()
    return _redis_service

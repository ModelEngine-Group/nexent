"""
Background scheduler that periodically checks knowledge bases with
auto-summary enabled and regenerates summaries as needed.
"""
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from consts.scheduler import (
    FREQUENCY_MAP,
    SCHEDULER_CHECK_INTERVAL_SECONDS,
)
from database.knowledge_db import get_knowledge_bases_for_auto_summary
from services.vectordatabase_service import ElasticSearchService, get_vector_db_core
from utils.config_utils import tenant_config_manager

logger = logging.getLogger(__name__)

# Check interval from centralized config
CHECK_INTERVAL_SECONDS = SCHEDULER_CHECK_INTERVAL_SECONDS

# Track knowledge bases currently being processed to avoid duplicates
_in_flight: set = set()


def _parse_last_summary_time(last_summary_time) -> Optional[datetime]:
    """Parse last_summary_time from various formats."""
    if last_summary_time is None:
        return None
    if isinstance(last_summary_time, datetime):
        return last_summary_time.replace(tzinfo=None)
    if isinstance(last_summary_time, str):
        try:
            return datetime.fromisoformat(last_summary_time)
        except (ValueError, TypeError):
            return None
    return None


def _is_due_for_summary(last_summary_time, frequency: str, last_doc_update_time) -> bool:
    """Check if a knowledge base is due for summary regeneration.
    
    Args:
        last_summary_time: Timestamp of last summary generation
        frequency: Summary frequency (e.g., '3h', '1d')
        last_doc_update_time: Timestamp of last document add/delete operation
    
    Returns:
        True if summary should be regenerated, False otherwise
    """
    interval = FREQUENCY_MAP.get(frequency)
    if interval is None:
        return False
    
    last = _parse_last_summary_time(last_summary_time)
    if last is None:
        return True  # Never summarized, do it now
    
    # Check if time interval has elapsed
    if (datetime.now() - last) < interval:
        return False
    
    # Check if there are new document changes since last summary
    doc_update = _parse_last_summary_time(last_doc_update_time)
    if doc_update is None:
        return True  # No doc update time recorded, assume need summary
    
    # Skip if no new documents since last summary
    if doc_update <= last:
        logger.info(f"Skipping summary: no document changes since last summary")
        return False
    
    return True


def _run_auto_summary_for_kb(index_name: str, tenant_id: str):
    """Run the summary generation for a single knowledge base."""
    if index_name in _in_flight:
        logger.info(f"Skipping {index_name}: already being processed")
        return

    _in_flight.add(index_name)
    try:
        logger.info(f"Starting auto-summary for knowledge base: {index_name}")
        vdb_core = get_vector_db_core()
        service = ElasticSearchService()

        from utils.document_vector_utils import (
            process_documents_for_clustering,
            kmeans_cluster_documents,
            summarize_clusters_map_reduce,
            merge_cluster_summaries,
        )

        # Get model_id from tenant config for LLM summarization
        model_id = None
        if tenant_id:
            try:
                tenant_config = tenant_config_manager.load_config(tenant_id)
                model_id_str = tenant_config.get("LLM_ID")
                if model_id_str:
                    model_id = int(model_id_str)
                    logger.info(f"Using LLM model ID {model_id} for auto-summary (tenant: {tenant_id})")
                else:
                    logger.warning(f"No LLM_ID configured for tenant {tenant_id}, summary will be placeholder only")
            except Exception as e:
                logger.warning(f"Failed to get LLM_ID from tenant config: {e}")

        sample_count = 40  # Smaller sample for auto-summary
        document_samples, doc_embeddings = process_documents_for_clustering(
            index_name=index_name,
            vdb_core=vdb_core,
            sample_doc_count=sample_count,
        )

        if not document_samples:
            logger.warning(f"No documents found for auto-summary: {index_name}")
            return

        clusters = kmeans_cluster_documents(doc_embeddings, k=None)
        cluster_summaries = summarize_clusters_map_reduce(
            document_samples=document_samples,
            clusters=clusters,
            language="zh",
            doc_max_words=100,
            cluster_max_words=150,
            model_id=model_id,
            tenant_id=tenant_id,
        )
        final_summary = merge_cluster_summaries(cluster_summaries)

        # Save the summary and update last_summary_time
        service.change_summary(
            index_name=index_name,
            summary_result=final_summary,
            user_id="auto_scheduler",
        )
        # change_summary already calls update_last_summary_time
        logger.info(f"Auto-summary completed for knowledge base: {index_name}")

    except Exception as e:
        logger.error(f"Auto-summary failed for {index_name}: {e}", exc_info=True)
    finally:
        _in_flight.discard(index_name)


def _scheduler_loop(stop_event: threading.Event):
    """Main scheduler loop that runs in a background thread."""
    logger.info("Auto-summary scheduler started")
    while not stop_event.is_set():
        try:
            kbs = get_knowledge_bases_for_auto_summary()
            logger.info(f"Checking {len(kbs)} knowledge bases for auto-summary")

            for kb in kbs:
                if stop_event.is_set():
                    break
                frequency = kb.get("summary_frequency")
                if _is_due_for_summary(
                    kb.get("last_summary_time"),
                    frequency,
                    kb.get("last_doc_update_time")
                ):
                    _run_auto_summary_for_kb(
                        index_name=kb["index_name"],
                        tenant_id=kb.get("tenant_id", ""),
                    )

        except Exception as e:
            logger.error(f"Auto-summary scheduler check failed: {e}", exc_info=True)

        # Wait for next check interval, but respond to stop_event
        stop_event.wait(timeout=CHECK_INTERVAL_SECONDS)

    logger.info("Auto-summary scheduler stopped")


class AutoSummaryScheduler:
    """Manages the auto-summary background thread."""

    def __init__(self):
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Start the scheduler thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("Auto-summary scheduler is already running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=_scheduler_loop,
            args=(self._stop_event,),
            daemon=True,
            name="auto-summary-scheduler",
        )
        self._thread.start()
        logger.info("Auto-summary scheduler thread started")

    def stop(self):
        """Signal the scheduler thread to stop."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=60)
            logger.info("Auto-summary scheduler thread stopped")


# Singleton instance
auto_summary_scheduler = AutoSummaryScheduler()

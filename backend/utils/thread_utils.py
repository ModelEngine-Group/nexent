import atexit
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


class GlobalThreadPool:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, max_workers=5):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance.pool = ThreadPoolExecutor(max_workers=max_workers)
                    instance.max_workers = max_workers
                    atexit.register(instance.pool.shutdown)
                    cls._instance = instance

        instance = cls._instance
        if max_workers != instance.max_workers:
            logger.warning(
                "GlobalThreadPool is already initialized with max_workers=%d; requested max_workers=%d is ignored",
                instance.max_workers,
                max_workers,
            )
        return instance

    def submit(self, fn, *args, **kwargs):
        return self.pool.submit(fn, *args, **kwargs)


pool = GlobalThreadPool(max_workers=5)


# Submit task asynchronously
def submit(fn, *args, **kwargs):
    return pool.submit(fn, *args, **kwargs)

import atexit
from concurrent.futures import ThreadPoolExecutor


class GlobalThreadPool:
    _instance = None

    def __new__(cls, max_workers=10):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.pool = ThreadPoolExecutor(max_workers=max_workers)
            atexit.register(cls._instance.pool.shutdown)
        return cls._instance

    def submit(self, fn, *args, **kwargs):
        return self.pool.submit(fn, *args, **kwargs)


pool = GlobalThreadPool(max_workers=5)


# Submit task asynchronously
def submit(fn, *args, **kwargs):
    return pool.submit(fn, *args, **kwargs)

import threading

from utils import thread_utils


class BlockingExecutor:
    def __init__(self, max_workers, construction_started, allow_construction):
        self._max_workers = max_workers
        self._construction_started = construction_started
        self._allow_construction = allow_construction
        self._construction_started.set()
        self._allow_construction.wait()

    def shutdown(self):
        pass


class CoordinatedLock:
    def __init__(self):
        self._lock = threading.Lock()
        self._entry_lock = threading.Lock()
        self._entries = 0
        self.first_entered = threading.Event()
        self.second_attempted = threading.Event()

    def __enter__(self):
        with self._entry_lock:
            self._entries += 1
            if self._entries == 1:
                self.first_entered.set()
            else:
                self.second_attempted.set()
        self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._lock.release()


def test_global_thread_pool_does_not_publish_before_executor_is_constructed(monkeypatch):
    construction_started = threading.Event()
    allow_construction = threading.Event()
    executor_constructions = []
    registered_shutdowns = []
    lock = CoordinatedLock()

    def create_executor(max_workers):
        executor_constructions.append(max_workers)
        return BlockingExecutor(max_workers, construction_started, allow_construction)

    monkeypatch.setattr(thread_utils.GlobalThreadPool, "_instance", None)
    monkeypatch.setattr(thread_utils.GlobalThreadPool, "_lock", lock)
    monkeypatch.setattr(thread_utils, "ThreadPoolExecutor", create_executor)
    monkeypatch.setattr(thread_utils.atexit, "register", registered_shutdowns.append)

    first_result = []
    second_result = []

    first = threading.Thread(target=lambda: first_result.append(thread_utils.GlobalThreadPool(max_workers=3)))

    def construct_second_pool():
        second_result.append(thread_utils.GlobalThreadPool(max_workers=7))

    second = threading.Thread(target=construct_second_pool)
    first.start()
    assert lock.first_entered.wait(timeout=1)
    assert construction_started.wait(timeout=1)

    second.start()
    assert lock.second_attempted.wait(timeout=1)

    allow_construction.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert not first.is_alive()
    assert not second.is_alive()
    assert first_result == second_result
    assert executor_constructions == [3]
    assert len(registered_shutdowns) == 1


def test_global_thread_pool_warns_when_later_worker_count_conflicts(monkeypatch, caplog):
    registered_shutdowns = []

    class Executor:
        def __init__(self, max_workers):
            self._max_workers = max_workers

        def shutdown(self):
            pass

    monkeypatch.setattr(thread_utils.GlobalThreadPool, "_instance", None)
    monkeypatch.setattr(thread_utils, "ThreadPoolExecutor", Executor)
    monkeypatch.setattr(thread_utils.atexit, "register", registered_shutdowns.append)

    initial_pool = thread_utils.GlobalThreadPool(max_workers=5)
    with caplog.at_level("WARNING", logger="utils.thread_utils"):
        later_pool = thread_utils.GlobalThreadPool(max_workers=9)

    assert later_pool is initial_pool
    assert later_pool.max_workers == 5
    assert "initialized with max_workers=5; requested max_workers=9 is ignored" in caplog.text
    assert len(registered_shutdowns) == 1


def test_global_thread_pool_submit_delegates_to_executor(monkeypatch):
    registered_shutdowns = []

    class Executor:
        def __init__(self, max_workers):
            self._max_workers = max_workers

        def submit(self, fn, *args, **kwargs):
            return fn(*args, **kwargs)

        def shutdown(self):
            pass

    monkeypatch.setattr(thread_utils.GlobalThreadPool, "_instance", None)
    monkeypatch.setattr(thread_utils, "ThreadPoolExecutor", Executor)
    monkeypatch.setattr(thread_utils.atexit, "register", registered_shutdowns.append)

    pool = thread_utils.GlobalThreadPool()

    assert pool.submit(lambda left, right: left + right, 2, 3) == 5

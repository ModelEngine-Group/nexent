class ThreadManagerError(RuntimeError):
    """Base exception for managed thread execution failures."""


class ThreadManagerNotRunning(ThreadManagerError):
    """Raised when work is submitted before the manager is started."""


class ThreadManagerDraining(ThreadManagerError):
    """Raised when work is submitted while the process is draining."""


class ThreadCapacityExceeded(ThreadManagerError):
    """Raised when a lane has no worker or queue capacity left."""

    def __init__(self, lane: str, capacity: int, queued: int):
        self.lane = lane
        self.capacity = capacity
        self.queued = queued
        super().__init__(f"Thread lane '{lane}' is full (capacity={capacity}, queued={queued})")


class InvalidThreadPolicy(ThreadManagerError, ValueError):
    """Raised when a lane policy cannot provide safe bounded execution."""

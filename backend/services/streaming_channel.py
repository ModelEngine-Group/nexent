"""
Streaming channel manager for enabling multiple SSE subscribers.

This module provides a mechanism for streaming chunks to multiple consumers,
which enables tab-switch recovery: when a user reconnects, they can subscribe
to the ongoing stream instead of starting a new one.
"""

import asyncio
import logging
from typing import Dict, Optional, AsyncIterator, List

logger = logging.getLogger(__name__)

# Default history buffer size (kept for backward compatibility with callers).
# The buffer is now unbounded so that resumed streams can replay all chunks.
DEFAULT_HISTORY_SIZE = 200


class StreamingChannel:
    """
    A channel that maintains a queue of streaming chunks for a conversation.
    Supports multiple subscribers by broadcasting chunks to all active consumers.

    Uses event-driven notification instead of polling:
    - _history_buffer: All published chunks kept for reconnection support
    - _data_event: asyncio.Event signaled when new data arrives
    """

    def __init__(
        self,
        conversation_id: str,
        user_id: str,
        history_size: int = DEFAULT_HISTORY_SIZE
    ):
        self.conversation_id = conversation_id
        self.user_id = user_id
        # Unbounded buffer so resume subscribers receive the full chunk history
        # even after long-running streams. Channels are cleaned up shortly after
        # stream completion (see _cleanup_channel_later in agent_service), so
        # memory pressure remains bounded by the conversation lifecycle.
        self._history_buffer: List[str] = []
        self._lock: asyncio.Lock = asyncio.Lock()
        self._data_event: asyncio.Event = asyncio.Event()
        self._subscribers: int = 0
        self._completed: bool = False
        self._completion_status: Optional[str] = None
        self._error: Optional[str] = None

    def add_subscriber(self):
        """Increment subscriber count."""
        self._subscribers += 1
        logger.debug(
            f"Added subscriber to channel {self.conversation_id}, "
            f"total: {self._subscribers}"
        )

    def remove_subscriber(self):
        """Decrement subscriber count."""
        self._subscribers = max(0, self._subscribers - 1)
        logger.debug(
            f"Removed subscriber from channel {self.conversation_id}, "
            f"total: {self._subscribers}"
        )

    @property
    def has_subscribers(self) -> bool:
        """Check if there are active subscribers."""
        return self._subscribers > 0

    @property
    def history_size(self) -> int:
        """Get the number of chunks in history."""
        return len(self._history_buffer)

    async def publish(self, chunk: str):
        """
        Add a chunk to the channel history for subscribers.
        Signals the data event to wake up waiting subscribers.
        Only publishes if not completed.
        """
        if self._completed:
            return

        async with self._lock:
            self._history_buffer.append(chunk)

        # Wake up waiting subscribers immediately
        self._data_event.set()

    def complete(self, status: str = 'completed'):
        """
        Mark the stream as completed.
        Status can be 'completed', 'failed', or 'stopped'.
        Signals completion to wake up waiting subscribers.
        """
        self._completed = True
        self._completion_status = status
        # Wake up waiting subscribers so they can exit
        self._data_event.set()
        logger.debug(
            f"Channel {self.conversation_id} marked as {status}"
        )

    def set_error(self, error: str):
        """Set an error on the channel."""
        self._error = error
        self._completed = True
        # Wake up waiting subscribers so they can exit
        self._data_event.set()
        logger.debug(f"Channel {self.conversation_id} error: {error}")

    @property
    def is_completed(self) -> bool:
        """Whether the channel has completed."""
        return self._completed

    @property
    def completion_status(self) -> Optional[str]:
        """Get the completion status."""
        return self._completion_status

    @property
    def error(self) -> Optional[str]:
        """Get the error message."""
        return self._error

    async def subscribe_with_history(self, start_from_index: int = 0) -> AsyncIterator[str]:
        """
        Subscribe with history: yields historical chunks from start_from_index,
        then continues waiting for new chunks until stream completes.
        Used for reconnection.

        Args:
            start_from_index: Index to start yielding historical chunks from.
                              Pass resume_from_unit_index to skip already-received chunks.
        """
        self.add_subscriber()
        try:
            async with self._lock:
                history_count = len(self._history_buffer)
                # Yield historical chunks starting from start_from_index
                for i in range(start_from_index, history_count):
                    yield self._history_buffer[i]

            # Wait for new chunks using event-driven approach
            last_yielded_index = history_count

            while True:
                # Check if completed first
                if self._completed:
                    # Drain any remaining chunks before exiting
                    async with self._lock:
                        current_size = len(self._history_buffer)
                        while last_yielded_index < current_size:
                            yield self._history_buffer[last_yielded_index]
                            last_yielded_index += 1
                    break

                # Wait for data event (with timeout to check completion)
                try:
                    await asyncio.wait_for(
                        self._data_event.wait(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    # Timeout, check if completed
                    continue

                # Clear the event and consume new data
                self._data_event.clear()

                async with self._lock:
                    current_size = len(self._history_buffer)
                    while last_yielded_index < current_size:
                        yield self._history_buffer[last_yielded_index]
                        last_yielded_index += 1
        finally:
            self.remove_subscriber()

    async def subscribe(self) -> AsyncIterator[str]:
        """
        Subscribe to new chunks only. Does not replay history.
        Used when frontend has already reconstructed state from database
        and only needs to receive new chunks going forward.
        """
        self.add_subscriber()
        try:
            async with self._lock:
                # Start from the current end of history
                last_yielded_index = len(self._history_buffer)

            while True:
                if self._completed:
                    break

                try:
                    await asyncio.wait_for(
                        self._data_event.wait(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                self._data_event.clear()

                async with self._lock:
                    current_size = len(self._history_buffer)
                    while last_yielded_index < current_size:
                        yield self._history_buffer[last_yielded_index]
                        last_yielded_index += 1
        finally:
            self.remove_subscriber()

    def get_history(self) -> List[str]:
        """Get all chunks in the history buffer (non-blocking)."""
        return list(self._history_buffer)


class StreamingChannelManager:
    """
    Singleton manager for streaming channels.
    Channels are identified by conversation_id.
    """

    _instance = None
    _lock = asyncio.Lock()
    _channels: Dict[str, StreamingChannel] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_channel_key(cls, conversation_id: int, user_id: str) -> str:
        """Generate a unique key for a channel."""
        return f"{user_id}:{conversation_id}"

    async def get_or_create_channel(
        self,
        conversation_id: int,
        user_id: str,
        history_size: int = DEFAULT_HISTORY_SIZE
    ) -> StreamingChannel:
        """
        Get an existing channel or create a new one.
        """
        key = self.get_channel_key(conversation_id, user_id)
        async with self._lock:
            if key not in self._channels:
                self._channels[key] = StreamingChannel(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    history_size=history_size
                )
                logger.debug(f"Created new channel: {key}")
            return self._channels[key]

    def get_channel(
        self,
        conversation_id: int,
        user_id: str
    ) -> Optional[StreamingChannel]:
        """Get an existing channel without creating one."""
        key = self.get_channel_key(conversation_id, user_id)
        return self._channels.get(key)

    async def complete_channel(
        self,
        conversation_id: int,
        user_id: str,
        status: str = 'completed'
    ):
        """Mark a channel as completed."""
        channel = self.get_channel(conversation_id, user_id)
        if channel:
            channel.complete(status)

    async def remove_channel(self, conversation_id: int, user_id: str):
        """Remove a channel from the manager."""
        key = self.get_channel_key(conversation_id, user_id)
        async with self._lock:
            if key in self._channels:
                del self._channels[key]
                logger.debug(f"Removed channel: {key}")

    def get_all_channels(self) -> Dict[str, StreamingChannel]:
        """Get all active channels (for debugging/monitoring)."""
        return dict(self._channels)

    def get_active_channel_count(self) -> int:
        """Get the number of active channels."""
        return len(self._channels)

    def has_active_subscribers(self, conversation_id: int, user_id: str) -> bool:
        """Check if a channel has active subscribers."""
        channel = self.get_channel(conversation_id, user_id)
        return channel is not None and channel.has_subscribers


# Global singleton instance
streaming_channel_manager = StreamingChannelManager()

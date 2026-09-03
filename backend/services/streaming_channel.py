"""
Streaming channel manager for enabling multiple SSE subscribers.

This module provides a mechanism for streaming chunks to multiple consumers,
which enables tab-switch recovery: when a user reconnects, they can subscribe
to the ongoing stream instead of starting a new one.
"""

import asyncio
from collections import deque
import logging
from typing import AsyncIterator, Deque, Dict, List, Optional, Tuple

from consts.const import RUNTIME_STREAM_LOCAL_REPLAY_MAX_BYTES
from services.runtime_state_service import runtime_state_service

logger = logging.getLogger(__name__)

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
        self._history_size = max(1, history_size)
        self._history_max_bytes = max(1, RUNTIME_STREAM_LOCAL_REPLAY_MAX_BYTES)
        self._history_buffer: Deque[Tuple[int, str, int]] = deque()
        self._history_bytes = 0
        self._next_event_index = 0
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

    @property
    def history_bytes(self) -> int:
        """Return retained UTF-8 payload bytes without copying payloads."""
        return self._history_bytes

    @property
    def history_start_index(self) -> int:
        """Return the absolute index of the oldest retained event."""
        if self._history_buffer:
            return self._history_buffer[0][0]
        return self._next_event_index

    def _snapshot_from(self, start_index: int) -> Tuple[List[str], int]:
        """Copy retained chunks at or after an absolute index."""
        effective_start = max(start_index, self.history_start_index)
        chunks = [
            chunk for index, chunk, _ in self._history_buffer
            if index >= effective_start
        ]
        return chunks, self._next_event_index

    async def publish(self, chunk: str):
        """
        Add a chunk to the channel history for subscribers.
        Signals the data event to wake up waiting subscribers.
        Only publishes if not completed.
        """
        if self._completed:
            return

        async with self._lock:
            chunk_bytes = len(chunk.encode("utf-8"))
            event_index = self._next_event_index
            self._next_event_index += 1
            self._history_buffer.append((event_index, chunk, chunk_bytes))
            self._history_bytes += chunk_bytes
            while len(self._history_buffer) > self._history_size or (
                self._history_bytes > self._history_max_bytes
                and len(self._history_buffer) > 1
            ):
                _, _, removed_bytes = self._history_buffer.popleft()
                self._history_bytes -= removed_bytes

        await runtime_state_service.append_stream_event_async(
            user_id=self.user_id,
            conversation_id=self.conversation_id,
            chunk=chunk,
        )

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
                historical_chunks, next_index = self._snapshot_from(start_from_index)

            # Never yield while holding the channel lock. A slow subscriber
            # must not prevent the producer from appending new chunks.
            for chunk in historical_chunks:
                yield chunk

            # Wait for new chunks using event-driven approach
            last_yielded_index = next_index

            while True:
                # Check if completed first
                if self._completed:
                    # Drain any remaining chunks before exiting
                    async with self._lock:
                        pending_chunks, last_yielded_index = self._snapshot_from(
                            last_yielded_index
                        )
                    for chunk in pending_chunks:
                        yield chunk
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
                    pending_chunks, last_yielded_index = self._snapshot_from(
                        last_yielded_index
                    )
                for chunk in pending_chunks:
                    yield chunk
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
                # Start from the current absolute end of history.
                last_yielded_index = self._next_event_index

            while True:
                if self._completed:
                    async with self._lock:
                        pending_chunks, last_yielded_index = self._snapshot_from(
                            last_yielded_index
                        )
                    for chunk in pending_chunks:
                        yield chunk
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
                    pending_chunks, last_yielded_index = self._snapshot_from(
                        last_yielded_index
                    )
                for chunk in pending_chunks:
                    yield chunk
        finally:
            self.remove_subscriber()

    def get_history(self) -> List[str]:
        """Get all chunks in the history buffer (non-blocking)."""
        return [chunk for _, chunk, _ in self._history_buffer]


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
            existing = self._channels.get(key)
            if existing is None or existing.is_completed:
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
        await runtime_state_service.mark_stream_completed_async(
            user_id=user_id,
            conversation_id=conversation_id,
            status=status,
        )

    async def remove_channel(
        self,
        conversation_id: int,
        user_id: str,
        expected_channel: Optional[StreamingChannel] = None,
    ):
        """Remove a channel from the manager."""
        key = self.get_channel_key(conversation_id, user_id)
        async with self._lock:
            current = self._channels.get(key)
            if current is not None and (
                expected_channel is None or current is expected_channel
            ):
                del self._channels[key]
                logger.debug(f"Removed channel: {key}")

    def get_all_channels(self) -> Dict[str, StreamingChannel]:
        """Get all active channels (for debugging/monitoring)."""
        return dict(self._channels)

    def get_active_channel_count(self) -> int:
        """Get the number of active channels."""
        return len(self._channels)

    def get_retained_history_bytes(self) -> int:
        """Return retained replay bytes across active channels."""
        return sum(channel.history_bytes for channel in self._channels.values())

    def has_active_subscribers(self, conversation_id: int, user_id: str) -> bool:
        """Check if a channel has active subscribers."""
        channel = self.get_channel(conversation_id, user_id)
        return channel is not None and channel.has_subscribers


# Global singleton instance
streaming_channel_manager = StreamingChannelManager()

"""
Unit tests for StreamingChannel event-driven implementation.
"""

import asyncio
import pytest

from backend.services.streaming_channel import (
    StreamingChannel,
    StreamingChannelManager,
    DEFAULT_HISTORY_SIZE,
)


class TestStreamingChannel:
    """Tests for StreamingChannel class."""

    @pytest.fixture
    def channel(self):
        """Create a fresh channel for each test."""
        return StreamingChannel(conversation_id="test-conv-1", user_id="test-user")

    @pytest.mark.asyncio
    async def test_publish_and_subscribe(self, channel):
        """Test basic publish and subscribe flow."""
        results = []
        
        async def consumer():
            async for chunk in channel.subscribe():
                results.append(chunk)
        
        # Start consumer
        consumer_task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)  # Give consumer time to start
        
        # Publish chunks
        await channel.publish("chunk1")
        await channel.publish("chunk2")
        await channel.publish("chunk3")
        
        # Complete the stream
        channel.complete()
        
        # Wait for consumer to finish
        await asyncio.wait_for(consumer_task, timeout=2.0)
        
        assert results == ["chunk1", "chunk2", "chunk3"]

    @pytest.mark.asyncio
    async def test_subscribe_with_history(self, channel):
        """Test subscribe_with_history yields historical chunks first."""
        # Publish some chunks before subscribing
        await channel.publish("hist1")
        await channel.publish("hist2")
        
        results = []
        
        async def consumer():
            async for chunk in channel.subscribe_with_history():
                results.append(chunk)
        
        # Subscribe after some history exists
        consumer_task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)
        
        # Publish more chunks
        await channel.publish("new1")
        await channel.publish("new2")
        
        # Complete
        channel.complete()
        await asyncio.wait_for(consumer_task, timeout=2.0)
        
        # Should have all chunks: history + new
        assert results == ["hist1", "hist2", "new1", "new2"]

    @pytest.mark.asyncio
    async def test_event_driven_notification(self, channel):
        """Test that subscribers are notified via events (not polling)."""
        results = []
        wakeup_count = 0
        
        async def consumer():
            nonlocal wakeup_count
            async for chunk in channel.subscribe():
                results.append(chunk)
        
        consumer_task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)
        
        # Publish with small delays to test event notification
        await channel.publish("a")
        await asyncio.sleep(0.01)
        await channel.publish("b")
        await asyncio.sleep(0.01)
        await channel.publish("c")
        
        channel.complete()
        await asyncio.wait_for(consumer_task, timeout=2.0)
        
        assert results == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_history_buffer_is_unbounded(self):
        """Test that history buffer is unbounded (stores all chunks).

        The buffer is intentionally unbounded to support stream resume
        after long-running streams. Memory is bounded by conversation lifecycle.
        """
        channel = StreamingChannel(
            conversation_id="test-conv",
            user_id="test-user",
            history_size=3  # This parameter is kept for API compatibility
        )

        for i in range(5):
            await channel.publish(f"chunk{i}")

        # All chunks should be kept (unbounded buffer)
        history = channel.get_history()
        assert len(history) == 5
        assert history == ["chunk0", "chunk1", "chunk2", "chunk3", "chunk4"]

    @pytest.mark.asyncio
    async def test_complete_wakes_up_subscribers(self, channel):
        """Test that complete() wakes up waiting subscribers."""
        results = []
        
        async def consumer():
            async for chunk in channel.subscribe():
                results.append(chunk)
        
        consumer_task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)
        
        # Don't publish anything, just complete
        channel.complete()
        
        # Consumer should exit (no chunks since nothing was published)
        await asyncio.wait_for(consumer_task, timeout=2.0)
        assert results == []

    @pytest.mark.asyncio
    async def test_error_sets_completed(self, channel):
        """Test that set_error marks channel as completed."""
        channel.set_error("Test error")
        
        assert channel.is_completed is True
        assert channel.error == "Test error"
        assert channel.completion_status is None

    @pytest.mark.asyncio
    async def test_subscriber_counting(self, channel):
        """Test subscriber count management."""
        assert channel.has_subscribers is False
        
        channel.add_subscriber()
        assert channel.has_subscribers is True
        
        channel.add_subscriber()
        assert channel._subscribers == 2
        
        channel.remove_subscriber()
        assert channel._subscribers == 1
        
        channel.remove_subscriber()
        channel.remove_subscriber()  # Should not go negative
        assert channel._subscribers == 0

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self, channel):
        """Test multiple concurrent subscribers."""
        results1 = []
        results2 = []
        
        async def consumer1():
            async for chunk in channel.subscribe():
                results1.append(chunk)
        
        async def consumer2():
            async for chunk in channel.subscribe():
                results2.append(chunk)
        
        t1 = asyncio.create_task(consumer1())
        t2 = asyncio.create_task(consumer2())
        await asyncio.sleep(0.05)
        
        await channel.publish("shared1")
        await channel.publish("shared2")
        
        channel.complete()
        
        await asyncio.wait_for(t1, timeout=2.0)
        await asyncio.wait_for(t2, timeout=2.0)
        
        # Both subscribers should receive all chunks
        assert results1 == ["shared1", "shared2"]
        assert results2 == ["shared1", "shared2"]


class TestStreamingChannelManager:
    """Tests for StreamingChannelManager singleton."""

    @pytest.fixture
    def manager(self):
        """Get a fresh manager instance (reset singleton for tests)."""
        # Reset singleton for clean test state
        StreamingChannelManager._instance = None
        StreamingChannelManager._channels = {}
        return StreamingChannelManager()

    @pytest.mark.asyncio
    async def test_get_or_create_channel(self, manager):
        """Test channel creation and retrieval."""
        channel1 = await manager.get_or_create_channel(
            conversation_id=123,
            user_id="user1"
        )
        channel2 = await manager.get_or_create_channel(
            conversation_id=123,
            user_id="user1"
        )
        
        # Should return same channel
        assert channel1 is channel2

    @pytest.mark.asyncio
    async def test_different_users_get_different_channels(self, manager):
        """Test that different users get different channels."""
        channel1 = await manager.get_or_create_channel(
            conversation_id=123,
            user_id="user1"
        )
        channel2 = await manager.get_or_create_channel(
            conversation_id=123,
            user_id="user2"
        )
        
        assert channel1 is not channel2

    @pytest.mark.asyncio
    async def test_get_channel(self, manager):
        """Test getting existing channel."""
        channel = await manager.get_or_create_channel(
            conversation_id=456,
            user_id="user1"
        )
        
        retrieved = manager.get_channel(conversation_id=456, user_id="user1")
        assert retrieved is channel
        
        # Non-existent should return None
        assert manager.get_channel(conversation_id=999, user_id="nobody") is None

    @pytest.mark.asyncio
    async def test_remove_channel(self, manager):
        """Test channel removal."""
        channel = await manager.get_or_create_channel(
            conversation_id=789,
            user_id="user1"
        )
        
        await manager.remove_channel(conversation_id=789, user_id="user1")
        
        # Should be removed
        assert manager.get_channel(conversation_id=789, user_id="user1") is None

    @pytest.mark.asyncio
    async def test_publish_to_channel(self, manager):
        """Test publishing a chunk to a channel via manager."""
        channel = await manager.get_or_create_channel(
            conversation_id=111,
            user_id="user1"
        )

        await channel.publish("test-chunk")

        assert channel.get_history() == ["test-chunk"]

    @pytest.mark.asyncio
    async def test_complete_channel_helper(self, manager):
        """Test complete_channel convenience method."""
        channel = await manager.get_or_create_channel(
            conversation_id=222,
            user_id="user1"
        )
        
        await manager.complete_channel(
            conversation_id=222,
            user_id="user1",
            status="completed"
        )
        
        assert channel.is_completed is True
        assert channel.completion_status == "completed"


class TestEventDrivenBehavior:
    """Tests specifically for event-driven behavior (no polling)."""

    @pytest.fixture
    def channel(self):
        """Create a fresh channel for each test."""
        return StreamingChannel(conversation_id="test-conv-evt", user_id="test-user")

    @pytest.mark.asyncio
    async def test_immediate_delivery(self, channel):
        """Test that data is delivered immediately after publish."""
        delivery_times = []

        async def consumer():
            async for chunk in channel.subscribe():
                delivery_times.append(asyncio.get_event_loop().time())
        
        consumer_task = asyncio.create_task(consumer())
        await asyncio.sleep(0.02)
        
        publish_time = asyncio.get_event_loop().time()
        await channel.publish("immediate")
        
        channel.complete()
        await asyncio.wait_for(consumer_task, timeout=2.0)
        
        # Delivery should be very close to publish time (within 100ms)
        delivery_latency = delivery_times[0] - publish_time
        assert delivery_latency < 0.1, f"Delivery took {delivery_latency}s, expected < 0.1s"

    @pytest.mark.asyncio
    async def test_concurrent_publish_and_subscribe(self, channel):
        """Test concurrent publishing and subscribing."""
        results = []

        async def publisher():
            for i in range(10):
                await channel.publish(f"p{i}")
                await asyncio.sleep(0.01)  # Small delay between publishes

        async def consumer():
            async for chunk in channel.subscribe():
                results.append(chunk)

        # Start both concurrently
        con_task = asyncio.create_task(consumer())
        pub_task = asyncio.create_task(publisher())

        # Wait for publisher to finish
        await pub_task
        await asyncio.sleep(0.05)  # Give consumer time to process
        channel.complete()

        await con_task

        # Consumer should receive all published chunks
        assert len(results) == 10
        assert results == [f"p{i}" for i in range(10)]

    @pytest.mark.asyncio
    async def test_subscribe_with_history_start_from_index(self, channel):
        """Test subscribe_with_history with start_from_index skips initial chunks."""
        # Publish some chunks before subscribing
        await channel.publish("hist0")
        await channel.publish("hist1")
        await channel.publish("hist2")
        await channel.publish("hist3")

        results = []

        async def consumer():
            # Start from index 2, so only hist2 and hist3 should be yielded from history
            async for chunk in channel.subscribe_with_history(start_from_index=2):
                results.append(chunk)

        consumer_task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)

        # Publish more chunks after subscribing
        await channel.publish("new1")
        await channel.publish("new2")

        channel.complete()
        await asyncio.wait_for(consumer_task, timeout=2.0)

        # Should only have hist2, hist3 + new chunks (not hist0 or hist1)
        assert results == ["hist2", "hist3", "new1", "new2"]

    @pytest.mark.asyncio
    async def test_subscribe_without_history(self, channel):
        """Test subscribe() only yields new chunks, not history."""
        # Publish some chunks before subscribing
        await channel.publish("old1")
        await channel.publish("old2")

        results = []

        async def consumer():
            async for chunk in channel.subscribe():
                results.append(chunk)

        consumer_task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)

        # Publish new chunks after subscribing
        await channel.publish("new1")
        await channel.publish("new2")

        channel.complete()
        await asyncio.wait_for(consumer_task, timeout=2.0)

        # Should only have new chunks, not the old history
        assert results == ["new1", "new2"]

    @pytest.mark.asyncio
    async def test_subscribe_resumes_from_current_position(self, channel):
        """Test subscribe() starts from current position, not replaying history.

        This test verifies that subscribe() only yields new chunks that arrive
        after subscription, not chunks that were already in the buffer.
        """
        # Publish some chunks
        await channel.publish("first1")
        await channel.publish("first2")

        # Subscribe and immediately complete
        results1 = []

        async def consumer1():
            async for chunk in channel.subscribe():
                results1.append(chunk)

        t1 = asyncio.create_task(consumer1())
        await asyncio.sleep(0.05)
        channel.complete()
        await asyncio.wait_for(t1, timeout=2.0)

        # Re-create channel for second test
        channel2 = StreamingChannel(conversation_id="test-conv-2", user_id="test-user")

        # Publish some chunks BEFORE subscribing
        await channel2.publish("before1")
        await channel2.publish("before2")

        # Now subscribe - should NOT see before1/before2 (subscribe starts from current position)
        results2 = []

        async def consumer2():
            async for chunk in channel2.subscribe():
                results2.append(chunk)

        t2 = asyncio.create_task(consumer2())
        await asyncio.sleep(0.05)

        # Publish new chunks AFTER subscribing - should see these
        await channel2.publish("after1")
        await channel2.publish("after2")

        channel2.complete()
        await asyncio.wait_for(t2, timeout=2.0)

        # First consumer got nothing (channel was empty when subscribed)
        assert results1 == []
        # Second consumer should only get after1, after2 (not before chunks)
        assert results2 == ["after1", "after2"]


class TestStreamingChannelEdgeCases:
    """Tests for edge cases and uncovered code paths."""

    @pytest.fixture
    def channel(self):
        """Create a fresh channel for each test."""
        return StreamingChannel(conversation_id="test-conv-edge", user_id="test-user")

    @pytest.fixture
    def manager(self):
        """Get a fresh manager instance (reset singleton for tests)."""
        StreamingChannelManager._instance = None
        StreamingChannelManager._channels = {}
        return StreamingChannelManager()

    @pytest.mark.asyncio
    async def test_publish_after_complete_is_noop(self, channel):
        """Test that publish() is a no-op after channel is completed.

        Line 83: if self._completed: return
        """
        channel.complete()

        # This should be a no-op
        await channel.publish("should-be-ignored")

        # History should be empty
        assert channel.get_history() == []

    @pytest.mark.asyncio
    async def test_subscribe_with_history_drains_on_completion(self, channel):
        """Test that subscribe_with_history drains remaining chunks when completed.

        Lines 156-157: drain remaining chunks before breaking on completion
        This tests the scenario where completion happens while there are still
        chunks in the buffer that haven't been yielded yet.
        """
        results = []

        async def consumer():
            async for chunk in channel.subscribe_with_history():
                results.append(chunk)

        consumer_task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)

        # Publish chunks while consumer is waiting
        await channel.publish("a")
        await channel.publish("b")

        # Complete the channel - consumer should drain remaining chunks
        channel.complete()

        await asyncio.wait_for(consumer_task, timeout=2.0)

        assert results == ["a", "b"]

    @pytest.mark.asyncio
    async def test_subscribe_with_history_completion_during_yield(self, channel):
        """Test subscribe_with_history drain when completion happens between checks.

        This tests lines 156-157 which handle the case where _completed
        is True and there are still chunks to drain.
        In asyncio this represents a defensive check for completion timing.
        """
        results = []

        async def consumer():
            async for chunk in channel.subscribe_with_history():
                results.append(chunk)

        consumer_task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)

        # Publish a chunk - consumer will pick it up
        await channel.publish("x")

        # Complete - this will trigger the drain path since
        # consumer is in wait state and event will be set
        channel.complete()

        await asyncio.wait_for(consumer_task, timeout=2.0)

        # Should receive at least the published chunk
        assert "x" in results

    @pytest.mark.asyncio
    async def test_subscribe_with_history_timeout_continues_loop(self, channel):
        """Test that TimeoutError in subscribe_with_history continues waiting.

        Lines 166-168: except asyncio.TimeoutError: continue
        """
        results = []

        async def consumer():
            async for chunk in channel.subscribe_with_history():
                results.append(chunk)

        consumer_task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)

        # Wait through timeout cycles (no data event for 1+ seconds)
        await asyncio.sleep(1.5)

        # Now publish - should still receive it
        await channel.publish("after-timeout")

        channel.complete()
        await asyncio.wait_for(consumer_task, timeout=2.0)

        assert results == ["after-timeout"]

    @pytest.mark.asyncio
    async def test_subscribe_timeout_continues_loop(self, channel):
        """Test that TimeoutError in subscribe continues waiting.

        Lines 202-203: except asyncio.TimeoutError: continue
        """
        results = []

        async def consumer():
            async for chunk in channel.subscribe():
                results.append(chunk)

        consumer_task = asyncio.create_task(consumer())
        await asyncio.sleep(0.05)

        # Wait through timeout cycles
        await asyncio.sleep(1.5)

        # Now publish - should still receive it
        await channel.publish("after-timeout")

        channel.complete()
        await asyncio.wait_for(consumer_task, timeout=2.0)

        assert results == ["after-timeout"]

    @pytest.mark.asyncio
    async def test_get_all_channels(self, manager):
        """Test get_all_channels returns all active channels.

        Line 290: return dict(self._channels)
        """
        await manager.get_or_create_channel(conversation_id=1, user_id="user1")
        await manager.get_or_create_channel(conversation_id=2, user_id="user1")
        await manager.get_or_create_channel(conversation_id=3, user_id="user2")

        all_channels = manager.get_all_channels()

        assert len(all_channels) == 3
        assert "user1:1" in all_channels
        assert "user1:2" in all_channels
        assert "user2:3" in all_channels

    @pytest.mark.asyncio
    async def test_get_active_channel_count(self, manager):
        """Test get_active_channel_count returns correct count.

        Line 294: return len(self._channels)
        """
        assert manager.get_active_channel_count() == 0

        await manager.get_or_create_channel(conversation_id=1, user_id="user1")
        assert manager.get_active_channel_count() == 1

        await manager.get_or_create_channel(conversation_id=2, user_id="user1")
        assert manager.get_active_channel_count() == 2

        await manager.remove_channel(conversation_id=1, user_id="user1")
        assert manager.get_active_channel_count() == 1

    @pytest.mark.asyncio
    async def test_has_active_subscribers(self, manager):
        """Test has_active_subscribers checks subscriber count.

        Lines 298-299: channel.has_subscribers
        """
        channel = await manager.get_or_create_channel(
            conversation_id=1, user_id="user1"
        )

        # No subscribers initially
        assert manager.has_active_subscribers(conversation_id=1, user_id="user1") is False

        # Add subscriber via channel
        channel.add_subscriber()
        assert manager.has_active_subscribers(conversation_id=1, user_id="user1") is True

        # Remove subscriber
        channel.remove_subscriber()
        assert manager.has_active_subscribers(conversation_id=1, user_id="user1") is False

    @pytest.mark.asyncio
    async def test_has_active_subscribers_nonexistent_channel(self, manager):
        """Test has_active_subscribers returns False for non-existent channel."""
        assert manager.has_active_subscribers(
            conversation_id=999, user_id="nobody"
        ) is False

    @pytest.mark.asyncio
    async def test_complete_with_status(self, channel):
        """Test complete() accepts different status values."""
        channel.complete(status="failed")
        assert channel.is_completed is True
        assert channel.completion_status == "failed"

    @pytest.mark.asyncio
    async def test_error_also_sets_completed(self, channel):
        """Test set_error() marks channel as completed."""
        channel.set_error("Something went wrong")
        assert channel.is_completed is True
        assert channel.error == "Something went wrong"
        # completion_status should be None for errors
        assert channel.completion_status is None

    @pytest.mark.asyncio
    async def test_history_size_property(self, channel):
        """Test history_size property returns correct count."""
        assert channel.history_size == 0

        await channel.publish("a")
        assert channel.history_size == 1

        await channel.publish("b")
        await channel.publish("c")
        assert channel.history_size == 3

    @pytest.mark.asyncio
    async def test_remove_subscriber_never_goes_negative(self, channel):
        """Test remove_subscriber clamps at 0."""
        channel.remove_subscriber()
        assert channel._subscribers == 0
        channel.remove_subscriber()
        assert channel._subscribers == 0

    @pytest.mark.asyncio
    async def test_manager_singleton(self, manager):
        """Test StreamingChannelManager is a singleton."""
        manager2 = StreamingChannelManager()
        assert manager is manager2

import pytest
import threading
from unittest.mock import Mock, MagicMock
from backend.agents.agent_run_manager import AgentRunManager, agent_run_manager
from nexent.core.agents.agent_context import ContextManagerConfig


class TestAgentRunManager:
    def setup_method(self):
        """Reset manager before each test"""
        # Create a fresh instance for testing
        self.manager = AgentRunManager()
        # Clear any existing state
        self.manager.agent_runs.clear()
        self.manager._conversation_context_managers.clear()
        self.manager._conversation_run_counts.clear()
        self.manager._context_manager_cache_max_size = 128

    def _complete_run_with_context(self, conversation_id: int):
        run_info = Mock()
        self.manager.register_agent_run(conversation_id, run_info, "user1")
        context_manager = self.manager.get_or_create_context_manager(
            conversation_id,
            ContextManagerConfig(enabled=True),
            max_steps=5,
        )
        self.manager.unregister_agent_run(conversation_id, "user1")
        return context_manager

    def test_context_manager_cache_evicts_least_recently_used_idle_entry(self):
        self.manager._context_manager_cache_max_size = 2
        first = self._complete_run_with_context(1)
        self._complete_run_with_context(2)

        # Reusing conversation 1 makes conversation 2 the LRU entry.
        self.manager.register_agent_run(1, Mock(), "user1")
        assert self.manager.get_or_create_context_manager(
            1, ContextManagerConfig(enabled=True), max_steps=5
        ) is first
        self.manager.unregister_agent_run(1, "user1")

        self._complete_run_with_context(3)

        assert list(self.manager._conversation_context_managers) == ["1", "3"]
        assert "2" not in self.manager._conversation_run_counts

    def test_context_manager_cache_never_evicts_active_conversation(self):
        self.manager._context_manager_cache_max_size = 1
        self.manager.register_agent_run(1, Mock(), "user1")
        active_manager = self.manager.get_or_create_context_manager(
            1, ContextManagerConfig(enabled=True), max_steps=5
        )

        self._complete_run_with_context(2)

        assert self.manager._conversation_context_managers["1"] is active_manager
        assert "2" not in self.manager._conversation_context_managers

        self.manager.unregister_agent_run(1, "user1")

    def test_run_count_is_removed_when_context_manager_is_disabled(self):
        self.manager.register_agent_run(1, Mock(), "user1")
        self.manager.unregister_agent_run(1, "user1")

        assert "1" not in self.manager._conversation_run_counts

    def test_singleton_pattern(self):
        """Test that AgentRunManager is a singleton"""
        manager1 = AgentRunManager()
        manager2 = AgentRunManager()
        assert manager1 is manager2

    def test_get_run_key(self):
        """Test _get_run_key method generates correct keys"""
        key1 = self.manager._get_run_key(123, "user1")
        key2 = self.manager._get_run_key(456, "user1")
        key3 = self.manager._get_run_key(123, "user2")
        
        assert key1 == "user1:123"
        assert key2 == "user1:456"
        assert key3 == "user2:123"
        assert key1 != key2
        assert key1 != key3
        assert key2 != key3

    def test_register_agent_run(self):
        """Test registering an agent run"""
        conversation_id = 123
        user_id = "user1"
        mock_run_info = Mock()
        
        self.manager.register_agent_run(conversation_id, mock_run_info, user_id)
        
        # Check that the run is registered with correct key
        run_key = f"{user_id}:{conversation_id}"
        assert run_key in self.manager.agent_runs
        assert self.manager.agent_runs[run_key] == mock_run_info

    def test_register_agent_run_multiple_users(self):
        """Test registering agent runs for multiple users with same conversation_id"""
        conversation_id = 123
        user1_id = "user1"
        user2_id = "user2"
        mock_run_info1 = Mock()
        mock_run_info2 = Mock()
        
        # Register runs for different users with same conversation_id
        self.manager.register_agent_run(conversation_id, mock_run_info1, user1_id)
        self.manager.register_agent_run(conversation_id, mock_run_info2, user2_id)
        
        # Both should be registered with different keys
        key1 = f"{user1_id}:{conversation_id}"
        key2 = f"{user2_id}:{conversation_id}"
        assert key1 in self.manager.agent_runs
        assert key2 in self.manager.agent_runs
        assert self.manager.agent_runs[key1] == mock_run_info1
        assert self.manager.agent_runs[key2] == mock_run_info2

    def test_register_agent_run_same_user_different_conversations(self):
        """Test registering agent runs for same user with different conversation_ids"""
        user_id = "user1"
        conv_id1 = 123
        conv_id2 = 456
        mock_run_info1 = Mock()
        mock_run_info2 = Mock()
        
        # Register runs for same user with different conversation_ids
        self.manager.register_agent_run(conv_id1, mock_run_info1, user_id)
        self.manager.register_agent_run(conv_id2, mock_run_info2, user_id)
        
        # Both should be registered with different keys
        key1 = f"{user_id}:{conv_id1}"
        key2 = f"{user_id}:{conv_id2}"
        assert key1 in self.manager.agent_runs
        assert key2 in self.manager.agent_runs
        assert self.manager.agent_runs[key1] == mock_run_info1
        assert self.manager.agent_runs[key2] == mock_run_info2

    def test_unregister_agent_run(self):
        """Test unregistering an agent run"""
        conversation_id = 123
        user_id = "user1"
        mock_run_info = Mock()
        
        # Register first
        self.manager.register_agent_run(conversation_id, mock_run_info, user_id)
        run_key = f"{user_id}:{conversation_id}"
        assert run_key in self.manager.agent_runs
        
        # Then unregister
        self.manager.unregister_agent_run(conversation_id, user_id)
        assert run_key not in self.manager.agent_runs

    def test_unregister_agent_run_nonexistent(self):
        """Test unregistering a non-existent agent run"""
        # Should not raise an exception
        self.manager.unregister_agent_run(999, "nonexistent_user")
        assert len(self.manager.agent_runs) == 0

    def test_get_agent_run_info(self):
        """Test getting agent run info"""
        conversation_id = 123
        user_id = "user1"
        mock_run_info = Mock()
        
        # Initially no run info
        assert self.manager.get_agent_run_info(conversation_id, user_id) is None
        
        # Register a run
        self.manager.register_agent_run(conversation_id, mock_run_info, user_id)
        
        # Should return the registered run info
        retrieved_info = self.manager.get_agent_run_info(conversation_id, user_id)
        assert retrieved_info == mock_run_info

    def test_get_agent_run_info_wrong_user(self):
        """Test getting agent run info with wrong user_id"""
        conversation_id = 123
        user1_id = "user1"
        user2_id = "user2"
        mock_run_info = Mock()
        
        # Register run for user1
        self.manager.register_agent_run(conversation_id, mock_run_info, user1_id)
        
        # Try to get run info for user2 (should return None)
        retrieved_info = self.manager.get_agent_run_info(conversation_id, user2_id)
        assert retrieved_info is None

    def test_stop_agent_run(self):
        """Test stopping an agent run"""
        conversation_id = 123
        user_id = "user1"
        mock_run_info = Mock()
        mock_stop_event = Mock()
        mock_run_info.stop_event = mock_stop_event
        
        # Register a run
        self.manager.register_agent_run(conversation_id, mock_run_info, user_id)
        
        # Stop the run
        result = self.manager.stop_agent_run(conversation_id, user_id)
        
        assert result is True
        mock_stop_event.set.assert_called_once()

    def test_stop_agent_run_nonexistent(self):
        """Test stopping a non-existent agent run"""
        result = self.manager.stop_agent_run(999, "nonexistent_user")
        assert result is False

    def test_stop_agent_run_wrong_user(self):
        """Test stopping an agent run with wrong user_id"""
        conversation_id = 123
        user1_id = "user1"
        user2_id = "user2"
        mock_run_info = Mock()
        
        # Register run for user1
        self.manager.register_agent_run(conversation_id, mock_run_info, user1_id)
        
        # Try to stop run for user2 (should return False)
        result = self.manager.stop_agent_run(conversation_id, user2_id)
        assert result is False

    def test_thread_safety(self):
        """Test thread safety of the manager"""
        conversation_id = 123
        user_id = "user1"
        mock_run_info = Mock()
        
        def register_run():
            self.manager.register_agent_run(conversation_id, mock_run_info, user_id)
        
        def unregister_run():
            self.manager.unregister_agent_run(conversation_id, user_id)
        
        # Create multiple threads
        threads = []
        for i in range(10):
            if i % 2 == 0:
                thread = threading.Thread(target=register_run)
            else:
                thread = threading.Thread(target=unregister_run)
            threads.append(thread)
        
        # Start all threads
        for thread in threads:
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # The manager should still be in a consistent state
        # (exact state depends on timing, but should not crash)
        assert isinstance(self.manager.agent_runs, dict)

    def test_debug_mode_same_conversation_id(self):
        """Test that debug mode with same conversation_id (-1) works for different users"""
        conversation_id = -1  # Debug mode
        user1_id = "user1"
        user2_id = "user2"
        mock_run_info1 = Mock()
        mock_run_info2 = Mock()
        
        # Register runs for different users with same conversation_id (-1)
        self.manager.register_agent_run(conversation_id, mock_run_info1, user1_id)
        self.manager.register_agent_run(conversation_id, mock_run_info2, user2_id)
        
        # Both should be registered with different keys
        key1 = f"{user1_id}:{conversation_id}"
        key2 = f"{user2_id}:{conversation_id}"
        assert key1 in self.manager.agent_runs
        assert key2 in self.manager.agent_runs
        assert self.manager.agent_runs[key1] == mock_run_info1
        assert self.manager.agent_runs[key2] == mock_run_info2
        
        # Should be able to get and stop each run independently
        retrieved1 = self.manager.get_agent_run_info(conversation_id, user1_id)
        retrieved2 = self.manager.get_agent_run_info(conversation_id, user2_id)
        assert retrieved1 == mock_run_info1
        assert retrieved2 == mock_run_info2
        
        # Stop one run, the other should still exist
        result1 = self.manager.stop_agent_run(conversation_id, user1_id)
        assert result1 is True
        
        # user1's run should be stopped, user2's should still exist
        retrieved1_after = self.manager.get_agent_run_info(conversation_id, user1_id)
        retrieved2_after = self.manager.get_agent_run_info(conversation_id, user2_id)
        assert retrieved1_after == mock_run_info1  # Still exists but stopped
        assert retrieved2_after == mock_run_info2  # Still exists and running

    def test_global_instance(self):
        """Test that the global agent_run_manager instance works"""
        conversation_id = 123
        user_id = "user1"
        mock_run_info = Mock()
        
        # Use the global instance
        agent_run_manager.register_agent_run(conversation_id, mock_run_info, user_id)
        
        # Should be able to retrieve it
        retrieved_info = agent_run_manager.get_agent_run_info(conversation_id, user_id)
        assert retrieved_info == mock_run_info
        
        # Should be able to stop it
        result = agent_run_manager.stop_agent_run(conversation_id, user_id)
        assert result is True
        
        # Clean up
        agent_run_manager.unregister_agent_run(conversation_id, user_id)

    def test_key_generation_edge_cases(self):
        """Test _get_run_key with edge cases"""
        # Test with empty string user_id
        key1 = self.manager._get_run_key(123, "")
        assert key1 == ":123"
        
        # Test with special characters in user_id
        key2 = self.manager._get_run_key(123, "user:with:colons")
        assert key2 == "user:with:colons:123"
        
        # Test with negative conversation_id
        key3 = self.manager._get_run_key(-1, "user1")
        assert key3 == "user1:-1"
        
        # Test with zero conversation_id
        key4 = self.manager._get_run_key(0, "user1")
        assert key4 == "user1:0"

    def test_concurrent_registration_same_key(self):
        """Test concurrent registration with same key (should overwrite)"""
        conversation_id = 123
        user_id = "user1"
        mock_run_info1 = Mock()
        mock_run_info2 = Mock()
        
        # Register first run
        self.manager.register_agent_run(conversation_id, mock_run_info1, user_id)
        
        # Register second run with same key (should overwrite)
        self.manager.register_agent_run(conversation_id, mock_run_info2, user_id)
        
        # Should have the second run info
        retrieved_info = self.manager.get_agent_run_info(conversation_id, user_id)
        assert retrieved_info == mock_run_info2
        assert retrieved_info != mock_run_info1

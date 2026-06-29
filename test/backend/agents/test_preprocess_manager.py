import pytest
import asyncio
from unittest.mock import Mock, AsyncMock
from backend.agents.preprocess_manager import PreprocessManager, PreprocessTask


class TestPreprocessManager:
    def setup_method(self):
        """Reset manager before each test"""
        self.manager = PreprocessManager()
        self.user_id = "user-1"
        self.tenant_id = "tenant-1"
        # Clear any existing state
        self.manager.preprocess_tasks.clear()
        self.manager.conversation_tasks.clear()

    def _identity_key(self, conversation_id, user_id=None, tenant_id=None):
        return (
            f"tenant={tenant_id or self.tenant_id}|"
            f"user={user_id or self.user_id}|"
            f"conversation={conversation_id}"
        )

    def test_singleton_pattern(self):
        """Test that PreprocessManager is a singleton"""
        manager1 = PreprocessManager()
        manager2 = PreprocessManager()
        assert manager1 is manager2

    def test_register_preprocess_task(self):
        """Test registering a preprocess task"""
        task_id = "test-task-1"
        conversation_id = 123
        mock_task = Mock()
        
        self.manager.register_preprocess_task(
            task_id, conversation_id, mock_task, user_id=self.user_id, tenant_id=self.tenant_id
        )
        
        assert task_id in self.manager.preprocess_tasks
        assert self._identity_key(conversation_id) in self.manager.conversation_tasks
        assert task_id in self.manager.conversation_tasks[self._identity_key(conversation_id)]
        
        task = self.manager.preprocess_tasks[task_id]
        assert task.task_id == task_id
        assert task.conversation_id == conversation_id
        assert task.user_id == self.user_id
        assert task.tenant_id == self.tenant_id
        assert task.task == mock_task
        assert task.is_running is True

    def test_unregister_preprocess_task(self):
        """Test unregistering a preprocess task"""
        task_id = "test-task-1"
        conversation_id = 123
        mock_task = Mock()
        
        # Register first
        self.manager.register_preprocess_task(
            task_id, conversation_id, mock_task, user_id=self.user_id, tenant_id=self.tenant_id
        )
        assert task_id in self.manager.preprocess_tasks
        
        # Then unregister
        self.manager.unregister_preprocess_task(task_id)
        assert task_id not in self.manager.preprocess_tasks
        assert self._identity_key(conversation_id) not in self.manager.conversation_tasks

    def test_stop_preprocess_tasks(self):
        """Test stopping preprocess tasks for a conversation"""
        task_id1 = "test-task-1"
        task_id2 = "test-task-2"
        conversation_id = 123
        mock_task1 = Mock()
        mock_task2 = Mock()
        
        # Register two tasks
        self.manager.register_preprocess_task(
            task_id1, conversation_id, mock_task1, user_id=self.user_id, tenant_id=self.tenant_id
        )
        self.manager.register_preprocess_task(
            task_id2, conversation_id, mock_task2, user_id=self.user_id, tenant_id=self.tenant_id
        )
        
        # Stop tasks
        result = self.manager.stop_preprocess_tasks(conversation_id, user_id=self.user_id, tenant_id=self.tenant_id)
        
        assert result is True
        assert not self.manager.preprocess_tasks[task_id1].is_running
        assert not self.manager.preprocess_tasks[task_id2].is_running

    def test_stop_preprocess_tasks_nonexistent(self):
        """Test stopping preprocess tasks for non-existent conversation"""
        result = self.manager.stop_preprocess_tasks(999, user_id=self.user_id, tenant_id=self.tenant_id)
        assert result is False

    def test_is_preprocess_running(self):
        """Test checking if preprocess is running"""
        task_id = "test-task-1"
        conversation_id = 123
        mock_task = Mock()
        
        # Initially no tasks running
        assert not self.manager.is_preprocess_running(conversation_id, user_id=self.user_id, tenant_id=self.tenant_id)
        
        # Register a task
        self.manager.register_preprocess_task(
            task_id, conversation_id, mock_task, user_id=self.user_id, tenant_id=self.tenant_id
        )
        assert self.manager.is_preprocess_running(conversation_id, user_id=self.user_id, tenant_id=self.tenant_id)
        
        # Stop the task
        self.manager.stop_preprocess_tasks(conversation_id, user_id=self.user_id, tenant_id=self.tenant_id)
        assert not self.manager.is_preprocess_running(conversation_id, user_id=self.user_id, tenant_id=self.tenant_id)

    def test_get_preprocess_status(self):
        """Test getting preprocess status"""
        task_id = "test-task-1"
        conversation_id = 123
        mock_task = Mock()
        
        # Initially no status
        status = self.manager.get_preprocess_status(conversation_id, user_id=self.user_id, tenant_id=self.tenant_id)
        assert status["running"] is False
        assert status["task_count"] == 0
        
        # Register a task
        self.manager.register_preprocess_task(
            task_id, conversation_id, mock_task, user_id=self.user_id, tenant_id=self.tenant_id
        )
        status = self.manager.get_preprocess_status(conversation_id, user_id=self.user_id, tenant_id=self.tenant_id)
        assert status["running"] is True
        assert status["task_count"] == 1
        assert len(status["tasks"]) == 1
        assert status["tasks"][0]["task_id"] == task_id

    def test_multiple_conversations(self):
        """Test handling multiple conversations"""
        task_id1 = "task-1"
        task_id2 = "task-2"
        conv_id1 = 123
        conv_id2 = 456
        mock_task1 = Mock()
        mock_task2 = Mock()
        
        # Register tasks for different conversations
        self.manager.register_preprocess_task(
            task_id1, conv_id1, mock_task1, user_id=self.user_id, tenant_id=self.tenant_id
        )
        self.manager.register_preprocess_task(
            task_id2, conv_id2, mock_task2, user_id=self.user_id, tenant_id=self.tenant_id
        )
        
        # Check status for each conversation
        status1 = self.manager.get_preprocess_status(conv_id1, user_id=self.user_id, tenant_id=self.tenant_id)
        status2 = self.manager.get_preprocess_status(conv_id2, user_id=self.user_id, tenant_id=self.tenant_id)
        
        assert status1["running"] is True
        assert status2["running"] is True
        assert status1["task_count"] == 1
        assert status2["task_count"] == 1
        
        # Stop one conversation
        self.manager.stop_preprocess_tasks(conv_id1, user_id=self.user_id, tenant_id=self.tenant_id)
        
        status1 = self.manager.get_preprocess_status(conv_id1, user_id=self.user_id, tenant_id=self.tenant_id)
        status2 = self.manager.get_preprocess_status(conv_id2, user_id=self.user_id, tenant_id=self.tenant_id)
        
        assert status1["running"] is False
        assert status2["running"] is True

    def test_same_conversation_id_different_tenants_do_not_collide(self):
        """Stopping one tenant's preprocess task leaves the colliding tenant untouched."""
        conversation_id = 123
        task_a = Mock()
        task_b = Mock()

        self.manager.register_preprocess_task(
            "task-a", conversation_id, task_a, user_id=self.user_id, tenant_id="tenant-a"
        )
        self.manager.register_preprocess_task(
            "task-b", conversation_id, task_b, user_id=self.user_id, tenant_id="tenant-b"
        )

        assert self.manager.stop_preprocess_tasks(
            conversation_id, user_id=self.user_id, tenant_id="tenant-a"
        )

        assert not self.manager.preprocess_tasks["task-a"].is_running
        assert self.manager.preprocess_tasks["task-b"].is_running
        assert self.manager.is_preprocess_running(
            conversation_id, user_id=self.user_id, tenant_id="tenant-b"
        )

    def test_user_id_required_for_preprocess_identity(self):
        with pytest.raises(ValueError):
            self.manager.register_preprocess_task("task", 123, Mock(), tenant_id=self.tenant_id)

    def test_tenant_id_required_for_preprocess_identity(self):
        with pytest.raises(ValueError):
            self.manager.register_preprocess_task("task", 123, Mock(), user_id=self.user_id)


class TestPreprocessTask:
    def test_preprocess_task_creation(self):
        """Test PreprocessTask creation"""
        task_id = "test-task"
        conversation_id = 123
        
        task = PreprocessTask(task_id, conversation_id)
        
        assert task.task_id == task_id
        assert task.conversation_id == conversation_id
        assert task.is_running is True
        assert task.task is None
        assert not task.stop_event.is_set()

    def test_stop_event(self):
        """Test stop event functionality"""
        task = PreprocessTask("test", 123)
        
        # Initially not set
        assert not task.stop_event.is_set()
        
        # Set the event
        task.stop_event.set()
        assert task.stop_event.is_set()
        
        # Clear the event
        task.stop_event.clear()
        assert not task.stop_event.is_set()

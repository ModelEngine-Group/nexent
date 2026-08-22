import pytest
import asyncio
from unittest.mock import Mock, AsyncMock
from backend.agents.preprocess_manager import PreprocessManager, PreprocessTask


class TestPreprocessManager:
    def setup_method(self):
        """Reset manager before each test"""
        self.manager = PreprocessManager()
        # Clear any existing state
        self.manager.preprocess_tasks.clear()
        self.manager.conversation_tasks.clear()

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
        
        self.manager.register_preprocess_task(task_id, conversation_id, mock_task)
        
        assert task_id in self.manager.preprocess_tasks
        assert conversation_id in self.manager.conversation_tasks
        assert task_id in self.manager.conversation_tasks[conversation_id]
        
        task = self.manager.preprocess_tasks[task_id]
        assert task.task_id == task_id
        assert task.conversation_id == conversation_id
        assert task.task == mock_task
        assert task.is_running is True

    def test_unregister_preprocess_task(self):
        """Test unregistering a preprocess task"""
        task_id = "test-task-1"
        conversation_id = 123
        mock_task = Mock()
        
        # Register first
        self.manager.register_preprocess_task(task_id, conversation_id, mock_task)
        assert task_id in self.manager.preprocess_tasks
        
        # Then unregister
        self.manager.unregister_preprocess_task(task_id)
        assert task_id not in self.manager.preprocess_tasks
        assert conversation_id not in self.manager.conversation_tasks

    def test_stop_preprocess_tasks(self):
        """Test stopping preprocess tasks for a conversation"""
        task_id1 = "test-task-1"
        task_id2 = "test-task-2"
        conversation_id = 123
        mock_task1 = Mock()
        mock_task2 = Mock()
        
        # Register two tasks
        self.manager.register_preprocess_task(task_id1, conversation_id, mock_task1)
        self.manager.register_preprocess_task(task_id2, conversation_id, mock_task2)
        
        # Stop tasks
        result = self.manager.stop_preprocess_tasks(conversation_id)
        
        assert result is True
        assert not self.manager.preprocess_tasks[task_id1].is_running
        assert not self.manager.preprocess_tasks[task_id2].is_running

    def test_stop_preprocess_tasks_nonexistent(self):
        """Test stopping preprocess tasks for non-existent conversation"""
        result = self.manager.stop_preprocess_tasks(999)
        assert result is False

    def test_is_preprocess_running(self):
        """Test checking if preprocess is running"""
        task_id = "test-task-1"
        conversation_id = 123
        mock_task = Mock()
        
        # Initially no tasks running
        assert not self.manager.is_preprocess_running(conversation_id)
        
        # Register a task
        self.manager.register_preprocess_task(task_id, conversation_id, mock_task)
        assert self.manager.is_preprocess_running(conversation_id)
        
        # Stop the task
        self.manager.stop_preprocess_tasks(conversation_id)
        assert not self.manager.is_preprocess_running(conversation_id)

    def test_get_preprocess_status(self):
        """Test getting preprocess status"""
        task_id = "test-task-1"
        conversation_id = 123
        mock_task = Mock()
        
        # Initially no status
        status = self.manager.get_preprocess_status(conversation_id)
        assert status["running"] is False
        assert status["task_count"] == 0
        
        # Register a task
        self.manager.register_preprocess_task(task_id, conversation_id, mock_task)
        status = self.manager.get_preprocess_status(conversation_id)
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
        self.manager.register_preprocess_task(task_id1, conv_id1, mock_task1)
        self.manager.register_preprocess_task(task_id2, conv_id2, mock_task2)
        
        # Check status for each conversation
        status1 = self.manager.get_preprocess_status(conv_id1)
        status2 = self.manager.get_preprocess_status(conv_id2)
        
        assert status1["running"] is True
        assert status2["running"] is True
        assert status1["task_count"] == 1
        assert status2["task_count"] == 1
        
        # Stop one conversation
        self.manager.stop_preprocess_tasks(conv_id1)
        
        status1 = self.manager.get_preprocess_status(conv_id1)
        status2 = self.manager.get_preprocess_status(conv_id2)
        
        assert status1["running"] is False
        assert status2["running"] is True


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
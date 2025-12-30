import pytest
import json
import time
from unittest.mock import MagicMock, patch
import os

# Create all necessary mocks
mock_paramiko = MagicMock()
mock_ssh_client = MagicMock()
mock_channel = MagicMock()
mock_transport = MagicMock()

# Configure paramiko mocks
mock_paramiko.SSHClient = mock_ssh_client
mock_paramiko.AutoAddPolicy = MagicMock()

# Use module-level mocks
module_mocks = {
    'paramiko': mock_paramiko,
}

# Apply mocks
with patch.dict('sys.modules', module_mocks):
    # Import all required modules
    from sdk.nexent.core.utils.observer import MessageObserver
    from sdk.nexent.core.utils.tools_common_message import ToolSign
    import sdk.nexent.core.tools.terminal_tool as terminal_tool_module


@pytest.fixture
def mock_observer():
    """Create a mock observer for testing"""
    observer = MagicMock(spec=MessageObserver)
    observer.lang = "en"
    return observer


@pytest.fixture
def mock_ssh_session():
    """Create a mock SSH session with client and channel"""
    client = MagicMock()
    channel = MagicMock()
    transport = MagicMock()
    
    # Configure channel behavior
    channel.closed = False
    channel.recv_ready.return_value = True
    channel.recv.return_value = b"test output\n$ "
    channel.send.return_value = None
    channel.get_transport.return_value = transport
    
    # Configure transport behavior
    transport.is_active.return_value = True
    
    # Configure client behavior
    client.connect.return_value = None
    client.invoke_shell.return_value = channel
    client.close.return_value = None
    
    return {
        "client": client,
        "channel": channel,
        "created_time": time.time()
    }


@pytest.fixture
def terminal_tool(mock_observer):
    """Create a TerminalTool instance for testing"""
    with patch.object(terminal_tool_module.paramiko, 'SSHClient') as mock_client_class, \
         patch('time.sleep'):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        tool = terminal_tool_module.TerminalTool(
            init_path="/test/path",
            observer=mock_observer,
            ssh_host="test-host",
            ssh_port=2222,
            ssh_user="testuser",
            password="testpass"
        )
        return tool


@pytest.fixture
def terminal_tool_no_observer():
    """Create a TerminalTool instance without observer for testing"""
    with patch.object(terminal_tool_module.paramiko, 'SSHClient') as mock_client_class, \
         patch('time.sleep'):
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        tool = terminal_tool_module.TerminalTool(
            init_path="~",
            observer=None,
            ssh_host="localhost",
            ssh_port=22,
            ssh_user="root",
            password="password"
        )
        return tool


class TestTerminalToolInitialization:
    """Test TerminalTool initialization"""
    
    def test_init_with_custom_path(self, mock_observer):
        """Test initialization with custom path"""
        with patch.object(terminal_tool_module.paramiko, 'SSHClient'):
            tool = terminal_tool_module.TerminalTool(
                init_path="/custom/path",
                observer=mock_observer,
                ssh_host="test-host",
                ssh_port=2222,
                ssh_user="testuser",
                password="testpass"
            )
            
            expected_path = os.path.abspath("/custom/path")
            assert tool.init_path == expected_path
            assert tool.observer == mock_observer
            assert tool.ssh_host == "test-host"
            assert tool.ssh_port == 2222
            assert tool.ssh_user == "testuser"
            assert tool.password == "testpass"
    
    def test_init_with_home_directory(self, mock_observer):
        """Test initialization with home directory"""
        with patch.object(terminal_tool_module.paramiko, 'SSHClient'):
            tool = terminal_tool_module.TerminalTool(
                init_path="~",
                observer=mock_observer,
                ssh_host="test-host",
                ssh_user="testuser",
                password="testpass"
            )
            
            assert tool.init_path == "~"
    
    def test_init_with_absolute_path(self, mock_observer):
        """Test initialization with absolute path"""
        with patch.object(terminal_tool_module.paramiko, 'SSHClient'):
            test_path = "/absolute/test/path"
            tool = terminal_tool_module.TerminalTool(
                init_path=test_path,
                observer=mock_observer,
                ssh_host="test-host",
                ssh_user="testuser",
                password="testpass"
            )
            
            assert tool.init_path == os.path.abspath(test_path)
    
    def test_init_without_observer(self):
        """Test initialization without observer"""
        with patch.object(terminal_tool_module.paramiko, 'SSHClient'):
            tool = terminal_tool_module.TerminalTool(
                init_path="~",
                observer=None,
                ssh_host="test-host",
                ssh_user="testuser",
                password="testpass"
            )
            
            assert tool.observer is None
            assert tool.ssh_host == "test-host"
            assert tool.ssh_user == "testuser"
            assert tool.password == "testpass"
    
    def test_tool_properties(self, terminal_tool):
        """Test tool class properties"""
        assert terminal_tool_module.TerminalTool.name == "terminal"
        assert "Execute shell commands" in terminal_tool_module.TerminalTool.description
        assert terminal_tool_module.TerminalTool.tool_sign == ToolSign.TERMINAL_OPERATION.value
        assert "command" in terminal_tool_module.TerminalTool.inputs
        assert terminal_tool_module.TerminalTool.output_type == "string"


class TestSessionManagement:
    """Test SSH session management"""
    
    def test_create_session_success(self, mock_observer, mock_ssh_session):
        """Test successful session creation"""
        with patch.object(terminal_tool_module.paramiko, 'SSHClient') as mock_client_class, \
             patch('time.sleep') as mock_sleep:  # Mock time.sleep to avoid delays
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_client.connect.return_value = None
            
            # Create a fresh mock channel to avoid conflicts with fixture
            mock_channel = MagicMock()
            mock_client.invoke_shell.return_value = mock_channel
            
            # Mock channel behavior for initial connection and cd command
            # First call: initial output available, second call: cd command output available
            mock_channel.recv_ready.side_effect = [True, True, True]
            mock_channel.recv.return_value = b"Welcome to SSH\n"
            mock_channel.send.return_value = None
            
            # Create tool instance within the patch context
            tool = terminal_tool_module.TerminalTool(
                init_path="/test/path",
                observer=mock_observer,
                ssh_host="test-host",
                ssh_port=2222,
                ssh_user="testuser",
                password="testpass"
            )
            
            session = tool._create_session()
            
            assert "client" in session
            assert "channel" in session
            assert "created_time" in session
    
    def test_create_session_no_init_path(self, mock_observer, mock_ssh_session):
        """Test session creation without init_path (no cd command)"""
        with patch.object(terminal_tool_module.paramiko, 'SSHClient') as mock_client_class, \
             patch('time.sleep') as mock_sleep:  # Mock time.sleep to avoid delays
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_client.connect.return_value = None
            
            # Create a fresh mock channel to avoid conflicts with fixture
            mock_channel = MagicMock()
            mock_client.invoke_shell.return_value = mock_channel
            
            # Mock channel behavior - no initial output
            mock_channel.recv_ready.return_value = False
            mock_channel.send.return_value = None
            
            # Create tool instance without init_path
            tool = terminal_tool_module.TerminalTool(
                init_path=None,  # No init path
                observer=mock_observer,
                ssh_host="test-host",
                ssh_port=2222,
                ssh_user="testuser",
                password="testpass"
            )
            
            session = tool._create_session()
            
            assert "client" in session
            assert "channel" in session
            assert "created_time" in session
            
            # Verify that no cd command was sent
            mock_channel.send.assert_not_called()
    
    def test_create_session_no_password(self, mock_observer):
        """Test session creation without password"""
        with patch.object(terminal_tool_module.paramiko, 'SSHClient'):
            tool = terminal_tool_module.TerminalTool(
                init_path="~",
                observer=mock_observer,
                ssh_host="test-host",
                ssh_user="testuser",
                password=""  # Empty password
            )
            
            with pytest.raises(ValueError, match="SSH password is required"):
                tool._create_session()
    
    def test_get_session_creates_new(self, terminal_tool, mock_ssh_session):
        """Test getting a new session"""
        with patch.object(terminal_tool, '_create_session') as mock_create, \
             patch('time.sleep'):
            mock_create.return_value = mock_ssh_session
            
            session = terminal_tool._get_session("test_session")
            
            assert session == mock_ssh_session
            mock_create.assert_called_once()
    
    def test_get_session_reuses_existing(self, terminal_tool, mock_ssh_session):
        """Test reusing existing session"""
        with patch.object(terminal_tool, '_create_session') as mock_create, \
             patch('time.sleep'):
            mock_create.return_value = mock_ssh_session
            with patch.object(terminal_tool, '_is_session_alive') as mock_alive:
                mock_alive.return_value = True
                
                # First call creates session
                session1 = terminal_tool._get_session("test_session")
                # Second call reuses session
                session2 = terminal_tool._get_session("test_session")
                
                assert session1 == session2
                mock_create.assert_called_once()  # Only called once
    
    def test_get_session_recreates_dead_session(self, terminal_tool, mock_ssh_session):
        """Test recreating dead session"""
        with patch.object(terminal_tool, '_create_session') as mock_create, \
             patch('time.sleep'):
            mock_create.return_value = mock_ssh_session
            with patch.object(terminal_tool, '_is_session_alive') as mock_alive:
                mock_alive.return_value = False
                with patch.object(terminal_tool, '_cleanup_session') as mock_cleanup:
                    
                    session = terminal_tool._get_session("test_session")
                    
                    mock_cleanup.assert_called_once()
                    assert mock_create.call_count == 2  # Called twice (create + recreate)
    
    def test_is_session_alive_true(self, terminal_tool, mock_ssh_session):
        """Test session alive check returns true"""
        mock_ssh_session["channel"].closed = False
        mock_ssh_session["channel"].get_transport.return_value.is_active.return_value = True
        
        result = terminal_tool._is_session_alive(mock_ssh_session)
        
        assert result is True
    
    def test_is_session_alive_false_closed_channel(self, terminal_tool, mock_ssh_session):
        """Test session alive check returns false for closed channel"""
        mock_ssh_session["channel"].closed = True
        
        result = terminal_tool._is_session_alive(mock_ssh_session)
        
        assert result is False
    
    def test_is_session_alive_false_inactive_transport(self, terminal_tool, mock_ssh_session):
        """Test session alive check returns false for inactive transport"""
        mock_ssh_session["channel"].closed = False
        mock_ssh_session["channel"].get_transport.return_value.is_active.return_value = False
        
        result = terminal_tool._is_session_alive(mock_ssh_session)
        
        assert result is False
    
    def test_is_session_alive_false_no_session(self, terminal_tool):
        """Test session alive check returns false for no session"""
        result = terminal_tool._is_session_alive(None)
        assert result is False
        
        result = terminal_tool._is_session_alive({})
        assert result is False
    
    def test_cleanup_session(self, terminal_tool, mock_ssh_session):
        """Test session cleanup"""
        terminal_tool._cleanup_session(mock_ssh_session)
        
        mock_ssh_session["channel"].close.assert_called_once()
        mock_ssh_session["client"].close.assert_called_once()
    
    def test_cleanup_session_handles_exceptions(self, terminal_tool):
        """Test session cleanup handles exceptions gracefully"""
        bad_session = {
            "channel": MagicMock(),
            "client": MagicMock()
        }
        bad_session["channel"].close.side_effect = Exception("Close failed")
        
        # Should not raise exception
        terminal_tool._cleanup_session(bad_session)


class TestOutputCleaning:
    """Test terminal output cleaning functionality"""
    
    def test_clean_output_basic(self, terminal_tool):
        """Test basic output cleaning"""
        raw_output = "user@host:~$ ls -la\nfile1.txt\nfile2.txt\nuser@host:~$ "
        command = "ls -la"
        
        result = terminal_tool._clean_output(raw_output, command)
        
        assert "file1.txt" in result
        assert "file2.txt" in result
        assert "user@host:~$" not in result
        assert "ls -la" not in result
    
    def test_clean_output_with_ansi_escape(self, terminal_tool):
        """Test output cleaning with ANSI escape sequences"""
        raw_output = "\x1B[32muser@host:~$\x1B[0m ls -la\n\x1B[34mfile1.txt\x1B[0m\nfile2.txt\n\x1B[32muser@host:~$\x1B[0m "
        command = "ls -la"
        
        result = terminal_tool._clean_output(raw_output, command)
        
        assert "file1.txt" in result
        assert "file2.txt" in result
        assert "\x1B[" not in result  # No ANSI escape sequences
    
    def test_clean_output_empty(self, terminal_tool):
        """Test cleaning empty output"""
        result = terminal_tool._clean_output("", "test")
        assert result == ""
        
        result = terminal_tool._clean_output(None, "test")
        assert result == ""
    
    def test_clean_output_removes_prompts(self, terminal_tool):
        """Test removing various shell prompts"""
        raw_output = "user@host:~$ ls\nfile1.txt\nuser@host:~$ "
        command = "ls"
        
        result = terminal_tool._clean_output(raw_output, command)
        
        assert "file1.txt" in result
        assert "$" not in result
        assert "#" not in result
    
    def test_clean_output_removes_bracketed_paste(self, terminal_tool):
        """Test removing bracketed paste mode sequences"""
        raw_output = "\x1b[?2004huser@host:~$ ls\nfile1.txt\n\x1b[?2004luser@host:~$ "
        command = "ls"
        
        result = terminal_tool._clean_output(raw_output, command)
        
        assert "file1.txt" in result
        assert "\x1b[?2004" not in result


class TestCommandExecution:
    """Test command execution functionality"""
    
    def test_execute_command_success(self, terminal_tool, mock_ssh_session):
        """Test successful command execution"""
        mock_channel = mock_ssh_session["channel"]
        mock_channel.recv_ready.return_value = True
        mock_channel.recv.return_value = b"test output\n$ "
        
        with patch.object(terminal_tool, '_clean_output') as mock_clean, \
             patch.object(terminal_tool_module.time, 'sleep'), \
             patch.object(terminal_tool_module.time, 'time') as mock_time:
            mock_clean.return_value = "cleaned output"
            # Mock time progression to avoid infinite loop
            mock_time.side_effect = [0, 0, 0, 31]  # Simulate timeout after a few iterations
            
            result = terminal_tool._execute_command(mock_channel, "ls", 30)
            
            assert result == "cleaned output"
            mock_channel.send.assert_called_with("ls\n")
            mock_clean.assert_called_once()
    
    def test_execute_command_timeout(self, terminal_tool, mock_ssh_session):
        """Test command execution timeout"""
        mock_channel = mock_ssh_session["channel"]
        mock_channel.recv_ready.return_value = False  # No output
        
        with patch('time.time') as mock_time, \
             patch('time.sleep'):
            mock_time.side_effect = [0, 0, 35]  # Timeout after 35 seconds
            
            result = terminal_tool._execute_command(mock_channel, "sleep 60", 30)
            
            assert "cleaned output" in result or result == ""
    
    def test_execute_command_exception(self, terminal_tool, mock_ssh_session):
        """Test command execution with exception"""
        mock_channel = mock_ssh_session["channel"]
        mock_channel.send.side_effect = Exception("Send failed")
        
        with patch('time.sleep'):
            result = terminal_tool._execute_command(mock_channel, "ls", 30)
            
            assert "Error executing command" in result
            assert "Send failed" in result
    
    def test_execute_command_prompt_detection_with_no_more_data(self, terminal_tool, mock_ssh_session):
        """Test command execution with prompt detection and no more data after prompt"""
        mock_channel = mock_ssh_session["channel"]
        
        # Simulate dynamic recv_ready behavior:
        # First call: data available, second call: no more data after prompt detection
        mock_channel.recv_ready.side_effect = [True, False]
        mock_channel.recv.return_value = b"file1.txt\nfile2.txt\n$ "
        
        with patch.object(terminal_tool, '_clean_output') as mock_clean, \
             patch('time.sleep'):
            mock_clean.return_value = "cleaned output"
            
            result = terminal_tool._execute_command(mock_channel, "ls", 30)
            
            assert result == "cleaned output"
            mock_channel.send.assert_called_with("ls\n")
            mock_clean.assert_called_once()
            # Verify recv_ready was called multiple times
            assert mock_channel.recv_ready.call_count >= 2
    
    def test_execute_command_multiple_prompt_types(self, terminal_tool, mock_ssh_session):
        """Test command execution with different prompt types (# and >)"""
        mock_channel = mock_ssh_session["channel"]
        
        # Test with # prompt (root shell)
        mock_channel.recv_ready.side_effect = [True, False]
        mock_channel.recv.return_value = b"root@server:~# "
        
        with patch.object(terminal_tool, '_clean_output') as mock_clean, \
             patch('time.sleep'):
            mock_clean.return_value = "cleaned output"
            
            result = terminal_tool._execute_command(mock_channel, "whoami", 30)
            
            assert result == "cleaned output"
            mock_channel.send.assert_called_with("whoami\n")
            mock_clean.assert_called_once()
    
    def test_execute_command_windows_prompt(self, terminal_tool, mock_ssh_session):
        """Test command execution with Windows prompt (>)"""
        mock_channel = mock_ssh_session["channel"]
        
        # Test with > prompt (Windows)
        mock_channel.recv_ready.side_effect = [True, False]
        mock_channel.recv.return_value = b"C:\\Users\\test> "
        
        with patch.object(terminal_tool, '_clean_output') as mock_clean, \
             patch('time.sleep'):
            mock_clean.return_value = "cleaned output"
            
            result = terminal_tool._execute_command(mock_channel, "dir", 30)
            
            assert result == "cleaned output"
            mock_channel.send.assert_called_with("dir\n")
            mock_clean.assert_called_once()
    
    def test_execute_command_no_output_timeout(self, terminal_tool, mock_ssh_session):
        """Test command execution with no output for extended period"""
        mock_channel = mock_ssh_session["channel"]
        
        # No data available, should timeout after 2 seconds of no output
        mock_channel.recv_ready.return_value = False
        
        with patch('time.time') as mock_time, \
             patch('time.sleep'):
            # Simulate time progression: start at 0, then 1 second, then 3 seconds (timeout)
            mock_time.side_effect = [0, 1, 3]
            
            result = terminal_tool._execute_command(mock_channel, "sleep 10", 30)
            
            # Should return empty or minimal output due to timeout
            assert isinstance(result, str)


class TestForwardMethod:
    """Test the main forward method"""
    
    def test_forward_success(self, terminal_tool, mock_ssh_session):
        """Test successful forward execution"""
        with patch.object(terminal_tool, '_get_session') as mock_get_session, \
             patch('time.sleep'):
            mock_get_session.return_value = mock_ssh_session
            with patch.object(terminal_tool, '_execute_command') as mock_execute:
                mock_execute.return_value = "command output"
                
                result = terminal_tool.forward("ls -la", "test_session", 30)
                
                result_data = json.loads(result)
                assert result_data["command"] == "ls -la"
                assert result_data["session_name"] == "test_session"
                assert result_data["output"] == "command output"
                assert "timestamp" in result_data
                
                mock_get_session.assert_called_with("test_session")
                mock_execute.assert_called_with(mock_ssh_session["channel"], "ls -la", 30)
    
    def test_forward_with_observer(self, terminal_tool, mock_ssh_session):
        """Test forward execution with observer"""
        with patch.object(terminal_tool, '_get_session') as mock_get_session, \
             patch('time.sleep'):
            mock_get_session.return_value = mock_ssh_session
            with patch.object(terminal_tool, '_execute_command') as mock_execute:
                mock_execute.return_value = "command output"
                
                terminal_tool.forward("ls -la", "test_session", 30)
                
                # Check observer calls
                assert terminal_tool.observer.add_message.call_count >= 2
                calls = terminal_tool.observer.add_message.call_args_list
                
                # Check for running prompt
                running_calls = [call for call in calls if "Executing terminal command" in str(call)]
                assert len(running_calls) > 0
                
                # Check for completion message
                completion_calls = [call for call in calls if "Command executed" in str(call)]
                assert len(completion_calls) > 0
    
    def test_forward_without_observer(self, terminal_tool_no_observer, mock_ssh_session):
        """Test forward execution without observer"""
        with patch.object(terminal_tool_no_observer, '_get_session') as mock_get_session, \
             patch('time.sleep'):
            mock_get_session.return_value = mock_ssh_session
            with patch.object(terminal_tool_no_observer, '_execute_command') as mock_execute:
                mock_execute.return_value = "command output"
                
                result = terminal_tool_no_observer.forward("ls -la", "test_session", 30)
                
                result_data = json.loads(result)
                assert result_data["command"] == "ls -la"
                assert result_data["output"] == "command output"
    
    def test_forward_exception(self, terminal_tool, mock_ssh_session):
        """Test forward execution with exception"""
        with patch.object(terminal_tool, '_get_session') as mock_get_session, \
             patch('time.sleep'):
            mock_get_session.side_effect = Exception("Session failed")
            
            result = terminal_tool.forward("ls -la", "test_session", 30)
            
            result_data = json.loads(result)
            assert result_data["command"] == "ls -la"
            assert result_data["session_name"] == "test_session"
            assert "error" in result_data
            assert "Session failed" in result_data["error"]
    
    def test_forward_default_parameters(self, terminal_tool, mock_ssh_session):
        """Test forward execution with default parameters"""
        with patch.object(terminal_tool, '_get_session') as mock_get_session, \
             patch('time.sleep'):
            mock_get_session.return_value = mock_ssh_session
            with patch.object(terminal_tool, '_execute_command') as mock_execute:
                mock_execute.return_value = "output"
                
                result = terminal_tool.forward("ls")
                
                result_data = json.loads(result)
                assert result_data["session_name"] == "default"
                mock_execute.assert_called_with(mock_ssh_session["channel"], "ls", 30)


class TestIntegration:
    """Integration tests"""
    
    def test_full_workflow(self, terminal_tool, mock_ssh_session):
        """Test complete workflow from initialization to command execution"""
        with patch.object(terminal_tool_module.paramiko, 'SSHClient') as mock_client_class, \
             patch.object(terminal_tool_module.time, 'sleep'), \
             patch.object(terminal_tool_module.time, 'time') as mock_time:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client
            mock_client.connect.return_value = None
            mock_client.invoke_shell.return_value = mock_ssh_session["channel"]
            
            # Mock channel behavior for command execution
            mock_ssh_session["channel"].recv_ready.return_value = True
            mock_ssh_session["channel"].recv.return_value = b"file1.txt\nfile2.txt\n$ "
            
            # Mock time progression to avoid infinite loop
            mock_time.side_effect = [0, 0, 0, 31, 1000, 1001, 1002, 1003, 1004, 1005]  # More values for other time.time() calls
            
            # Execute command
            result = terminal_tool.forward("ls", "integration_test", 30)
            
            result_data = json.loads(result)
            assert result_data["command"] == "ls"
            assert result_data["session_name"] == "integration_test"
            assert "timestamp" in result_data
    
    def test_multiple_commands_same_session(self, terminal_tool, mock_ssh_session):
        """Test multiple commands using the same session"""
        with patch.object(terminal_tool, '_get_session') as mock_get_session, \
             patch('time.sleep'):
            mock_get_session.return_value = mock_ssh_session
            with patch.object(terminal_tool, '_execute_command') as mock_execute:
                mock_execute.return_value = "output"
                
                # Execute multiple commands
                result1 = terminal_tool.forward("ls", "shared_session", 30)
                result2 = terminal_tool.forward("pwd", "shared_session", 30)
                
                # Should reuse the same session
                assert mock_get_session.call_count == 2
                assert mock_execute.call_count == 2
                
                # Both should succeed
                data1 = json.loads(result1)
                data2 = json.loads(result2)
                assert data1["session_name"] == "shared_session"
                assert data2["session_name"] == "shared_session"

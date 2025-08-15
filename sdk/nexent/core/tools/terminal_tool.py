import json
import logging
import os
import re
import time
from typing import Dict, Any
from pydantic import Field
from smolagents.tools import Tool
import paramiko

from ..utils.observer import MessageObserver, ProcessType

logger = logging.getLogger("terminal_tool")


class TerminalTool(Tool):
    """Terminal tool for executing shell commands via SSH"""
    name = "terminal"
    description = "Execute shell commands on a remote terminal via SSH connection. " \
                  "Supports session management to maintain shell state across commands. " \
                  "Uses private key authentication with root user by default. " \
                  "Returns the command output as a string."

    inputs = {
        "command": {"type": "string", "description": "Shell command to execute (e.g., 'ls -la', 'cd /var/log')"},
        "session_name": {"type": "string", "description": "Session name for connection reuse. Default is 'default'", "default": "default", "nullable": True},
        "timeout": {"type": "integer", "description": "Command timeout in seconds. Default is 30", "default": 30, "nullable": True}
    }
    output_type = "string"

    tool_sign = "t"  # Terminal operation tool identifier

    # Class-level session storage
    _sessions: Dict[str, Dict[str, Any]] = {}

    def __init__(self, 
                 init_path: str = Field(description="Initial workspace path", default="/mnt/nexent"),
                 observer: MessageObserver = Field(description="Message observer", default=None, exclude=True),
                 ssh_host: str = Field(description="SSH host", default="nexent-openssh-server"),
                 ssh_port: int = Field(description="SSH port", default=22),
                 ssh_user: str = Field(description="SSH username", default="linuxserver.io"),
                 private_key_path: str = Field(description="Path to private key file", default="/opt/ssh-keys/openssh_server_key")):
        """Initialize the TerminalTool.
        
        Args:
            init_path (str): Initial workspace path. Defaults to "/mnt/nexent".
            observer (MessageObserver, optional): Message observer instance. Defaults to None.
            ssh_host (str): SSH server host. Defaults to "localhost".
            ssh_port (int): SSH server port. Defaults to 22.
            ssh_user (str): SSH username. Defaults to "root".
            private_key_path (str): Path to SSH private key. Defaults to "~/.ssh/id_rsa".
        """
        super().__init__()
        self.init_path = os.path.abspath(init_path)
        self.observer = observer
        self.ssh_host = ssh_host
        self.ssh_port = ssh_port
        self.ssh_user = ssh_user
        self.private_key_path = os.path.expanduser(private_key_path)
        self.running_prompt_zh = "正在执行终端命令..."
        self.running_prompt_en = "Executing terminal command..."

    def _get_session(self, session_name: str) -> Dict[str, Any]:
        """Get or create SSH session.
        
        Args:
            session_name (str): Session identifier
            
        Returns:
            Dict containing SSH client and channel
        """
        if session_name not in self._sessions:
            self._sessions[session_name] = self._create_session()
        
        session = self._sessions[session_name]
        
        # Check if connection is still alive
        if not self._is_session_alive(session):
            logger.info(f"Session {session_name} is dead, recreating...")
            self._cleanup_session(session)
            self._sessions[session_name] = self._create_session()
            session = self._sessions[session_name]
            
        return session

    def _create_session(self) -> Dict[str, Any]:
        """Create new SSH session.
        
        Returns:
            Dict containing SSH client and channel
            
        Raises:
            Exception: If SSH connection fails
        """
        try:
            # Create SSH client
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # Load ED25519 private key
            if os.path.exists(self.private_key_path):
                private_key = paramiko.Ed25519Key.from_private_key_file(self.private_key_path)
                client.connect(
                    hostname=self.ssh_host,
                    port=self.ssh_port,
                    username=self.ssh_user,
                    pkey=private_key,
                    timeout=10
                )
            else:
                raise FileNotFoundError(f"Private key not found: {self.private_key_path}")
            
            # Create interactive shell
            channel = client.invoke_shell()
            time.sleep(1)  # Wait for shell initialization
            
            # Clear initial output
            if channel.recv_ready():
                channel.recv(4096)
            
            logger.info(f"SSH session created successfully: {self.ssh_user}@{self.ssh_host}:{self.ssh_port}")
            
            return {
                "client": client,
                "channel": channel,
                "created_time": time.time()
            }
            
        except Exception as e:
            logger.error(f"Failed to create SSH session: {str(e)}")
            raise

    def _is_session_alive(self, session: Dict[str, Any]) -> bool:
        """Check if SSH session is still alive.
        
        Args:
            session: Session dictionary
            
        Returns:
            bool: True if session is alive
        """
        try:
            if not session or "channel" not in session:
                return False
            
            channel = session["channel"]
            if channel.closed:
                return False
                
            # Send a simple test command
            transport = channel.get_transport()
            if transport and transport.is_active():
                return True
                
            return False
        except:
            return False

    def _cleanup_session(self, session: Dict[str, Any]):
        """Clean up SSH session resources.
        
        Args:
            session: Session dictionary to cleanup
        """
        try:
            if session and "channel" in session:
                session["channel"].close()
            if session and "client" in session:
                session["client"].close()
        except:
            pass

    def _clean_output(self, raw_output: str, command: str) -> str:
        """Clean terminal output by removing control characters and prompts.
        
        Args:
            raw_output: Raw terminal output
            command: The executed command
            
        Returns:
            str: Cleaned output
        """
        if not raw_output:
            return ""
        
        # Remove ANSI escape sequences (colors, cursor control, etc.)
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        cleaned = ansi_escape.sub('', raw_output)
        
        # Remove bracketed paste mode sequences
        cleaned = re.sub(r'\x1b\[\?2004[lh]', '', cleaned)
        
        # Split into lines and process
        lines = cleaned.split('\n')
        result_lines = []
        
        # Remove the echo of the command itself (first occurrence)
        command_found = False
        for line in lines:
            line = line.strip('\r\n ')
            
            # Skip empty lines at the beginning
            if not line and not result_lines:
                continue
                
            # Skip the command echo (usually the first non-empty line)
            if not command_found and command.strip() in line:
                command_found = True
                continue
            
            # Skip shell prompts (lines ending with $ or #)
            if re.match(r'.*[@#$]\s*$', line):
                continue
                
            # Skip lines that look like shell prompts with hostname
            if re.match(r'^[^@]*@[^:]*:[^$]*\$\s*$', line):
                continue
                
            if line:  # Only add non-empty lines
                result_lines.append(line)
        
        # Join the cleaned lines
        result = '\n'.join(result_lines).strip()
        
        return result

    def _execute_command(self, channel, command: str, timeout: int = 30) -> str:
        """Execute command on SSH channel.
        
        Args:
            channel: SSH channel
            command: Command to execute
            timeout: Command timeout in seconds
            
        Returns:
            str: Command output
        """
        try:
            # Send command
            channel.send(command + "\n")
            time.sleep(0.5)
            
            # Collect output
            output = ""
            start_time = time.time()
            last_output_time = start_time
            
            while time.time() - start_time < timeout:
                if channel.recv_ready():
                    chunk = channel.recv(1024).decode('utf-8', errors='ignore')
                    output += chunk
                    last_output_time = time.time()
                    
                # Check for prompt (command completion)
                if output and ('$ ' in output[-20:] or '# ' in output[-20:] or '> ' in output[-20:]):
                    time.sleep(0.5)
                    if not channel.recv_ready():
                        break
                
                # If no output for a while, command might be complete
                if time.time() - last_output_time > 2:
                    break
                    
                time.sleep(0.1)
            
            # Clean the output before returning
            cleaned_output = self._clean_output(output, command)
            return cleaned_output
            
        except Exception as e:
            logger.error(f"Command execution error: {str(e)}")
            return f"Error executing command: {str(e)}"

    def forward(self, command: str, session_name: str = "default", timeout: int = 30) -> str:
        """Execute terminal command via SSH.
        
        Args:
            command (str): Shell command to execute
            session_name (str): Session name for connection reuse
            timeout (int): Command timeout in seconds
            
        Returns:
            str: Command execution result
        """
        if self.observer:
            running_prompt = self.running_prompt_zh if self.observer.lang == "zh" else self.running_prompt_en
            self.observer.add_message("", ProcessType.TOOL, running_prompt)
            card_content = [{"icon": "terminal", "text": f"Executing: {command}"}]
            self.observer.add_message("", ProcessType.CARD, json.dumps(card_content, ensure_ascii=False))

        try:
            # Get or create session
            session = self._get_session(session_name)
            channel = session["channel"]
            
            # Execute command
            result = self._execute_command(channel, command, timeout)
            
            # Prepare result
            result_data = {
                "command": command,
                "session_name": session_name,
                "output": result,
                "timestamp": time.time()
            }
            
            if self.observer:
                self.observer.add_message("", ProcessType.TOOL, f"Command executed: {command}")
            
            return json.dumps(result_data, ensure_ascii=False, indent=2)
            
        except Exception as e:
            error_msg = f"Terminal command execution failed: {str(e)}"
            logger.error(error_msg)
            
            if self.observer:
                self.observer.add_message("", ProcessType.TOOL, error_msg)
            
            return json.dumps({
                "command": command,
                "session_name": session_name,
                "error": str(e),
                "timestamp": time.time()
            }, ensure_ascii=False, indent=2)

    @classmethod
    def cleanup_all_sessions(cls):
        """Clean up all active sessions."""
        for session_name, session in cls._sessions.items():
            try:
                if session and "channel" in session:
                    session["channel"].close()
                if session and "client" in session:
                    session["client"].close()
            except:
                pass
        cls._sessions.clear()
        logger.info("All SSH sessions cleaned up")


if __name__ == "__main__":
    """Test the TerminalTool functionality"""
    import sys
    
    # Basic configuration - 直接创建实例并设置属性
    tool = TerminalTool.__new__(TerminalTool)
    Tool.__init__(tool)
    tool.init_path = "/mnt/nexent"
    tool.observer = None
    tool.ssh_host = "localhost"  # For local testing
    tool.ssh_port = 2222
    tool.ssh_user = "linuxserver.io"
    tool.private_key_path = "/Users/shuangruichen/Code/nexent/docker/openssh-server/ssh-keys/openssh_server_key"
    tool.running_prompt_zh = "正在执行终端命令..."
    tool.running_prompt_en = "Executing terminal command..."
    
    print("=== Terminal Tool Test ===")
    print("Make sure openssh-server container is running and SSH keys are configured.")
    print("Commands to test: 'ls -la', 'pwd', 'whoami', 'echo \"Hello World\"', 'exit'")
    print()
    
    try:
        while True:
            command = input("Enter command (or 'quit' to exit): ").strip()
            
            if command.lower() in ['quit', 'exit']:
                break
                
            if not command:
                continue
                
            print(f"\n>>> Executing: {command}")
            result = tool.forward(command, session_name="test_session", timeout=30)
            print(f"Result: {result}")
            print("-" * 50)
            
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
    except Exception as e:
        print(f"Test error: {e}")
    finally:
        print("Cleaning up sessions...")
        TerminalTool.cleanup_all_sessions()
        print("Test completed.") 
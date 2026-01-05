"""
Unit tests for docker_config.py
Tests the DockerContainerConfig class
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from nexent.container.docker_config import DockerContainerConfig


class TestDockerContainerConfig:
    """Test cases for DockerContainerConfig class"""

    def test_init_with_no_parameters(self):
        """Test initialization with no parameters"""
        config = DockerContainerConfig()

        assert config._docker_socket_path is None
        assert config._base_url is None

    def test_init_with_docker_socket_path(self):
        """Test initialization with docker_socket_path"""
        config = DockerContainerConfig(docker_socket_path="/custom/socket/path")

        assert config._docker_socket_path == "/custom/socket/path"




    def test_container_type_property(self):
        """Test container_type property returns 'docker'"""
        config = DockerContainerConfig()
        
        assert config.container_type == "docker"

    def test_base_url_property_cached(self):
        """Test that base_url property is cached"""
        config = DockerContainerConfig()

        url1 = config.base_url
        url2 = config.base_url

        assert url1 == url2
        assert config._base_url is not None



    @patch('sys.platform', 'win32')
    def test_base_url_windows_default_socket(self):
        """Test base_url uses Windows default socket path"""
        config = DockerContainerConfig()
        
        assert config.base_url == "npipe:////./pipe/docker_engine"

    @patch('sys.platform', 'linux')
    def test_base_url_unix_default_socket(self):
        """Test base_url uses Unix default socket path"""
        config = DockerContainerConfig()
        
        assert config.base_url == "unix:///var/run/docker.sock"

    @patch('sys.platform', 'darwin')
    def test_base_url_darwin_default_socket(self):
        """Test base_url uses Unix default socket path on macOS"""
        config = DockerContainerConfig()
        
        assert config.base_url == "unix:///var/run/docker.sock"

    @patch('sys.platform', 'win32')
    def test_base_url_windows_custom_socket(self):
        """Test base_url with Windows custom socket path"""
        config = DockerContainerConfig(docker_socket_path="//./pipe/custom_pipe")
        
        assert config.base_url == "npipe:////./pipe/custom_pipe"

    @patch('sys.platform', 'linux')
    def test_base_url_unix_custom_socket(self):
        """Test base_url with Unix custom socket path"""
        config = DockerContainerConfig(docker_socket_path="/custom/socket/path")
        
        assert config.base_url == "unix:///custom/socket/path"


    @patch('sys.platform', 'win32')
    def test_normalize_base_url_windows_empty(self):
        """Test _normalize_base_url on Windows with empty value"""
        config = DockerContainerConfig()
        result = config._normalize_base_url("")
        
        assert result == "npipe:////./pipe/docker_engine"

    @patch('sys.platform', 'win32')
    def test_normalize_base_url_windows_named_pipe_forward_slash(self):
        """Test _normalize_base_url on Windows with //./pipe/ format"""
        config = DockerContainerConfig()
        result = config._normalize_base_url("//./pipe/docker_engine")
        
        assert result == "npipe:////./pipe/docker_engine"

    @patch('sys.platform', 'win32')
    def test_normalize_base_url_windows_named_pipe_backslash(self):
        """Test _normalize_base_url on Windows with \\.\\pipe\\ format"""
        config = DockerContainerConfig()
        result = config._normalize_base_url(r"\\.\pipe\docker_engine")
        
        assert result == r"npipe://\\.\pipe\docker_engine"

    @patch('sys.platform', 'win32')
    def test_normalize_base_url_windows_other_value(self):
        """Test _normalize_base_url on Windows with other value"""
        config = DockerContainerConfig()
        result = config._normalize_base_url("some-value")
        
        assert result == "npipe://some-value"

    @patch('sys.platform', 'linux')
    def test_normalize_base_url_unix_empty(self):
        """Test _normalize_base_url on Unix with empty value"""
        config = DockerContainerConfig()
        result = config._normalize_base_url("")
        
        assert result == "unix:///var/run/docker.sock"

    @patch('sys.platform', 'linux')
    def test_normalize_base_url_unix_absolute_path(self):
        """Test _normalize_base_url on Unix with absolute path"""
        config = DockerContainerConfig()
        result = config._normalize_base_url("/custom/socket/path")
        
        assert result == "unix:///custom/socket/path"

    @patch('sys.platform', 'linux')
    def test_normalize_base_url_unix_relative_path(self):
        """Test _normalize_base_url on Unix with relative path"""
        config = DockerContainerConfig()
        result = config._normalize_base_url("relative/path")
        
        assert result == "relative/path"

    @patch('sys.platform', 'linux')
    def test_normalize_base_url_unix_with_scheme(self):
        """Test _normalize_base_url on Unix with existing scheme"""
        config = DockerContainerConfig()
        result = config._normalize_base_url("unix:///var/run/docker.sock")
        
        assert result == "unix:///var/run/docker.sock"

    @patch('sys.platform', 'darwin')
    def test_normalize_base_url_darwin_absolute_path(self):
        """Test _normalize_base_url on macOS with absolute path"""
        config = DockerContainerConfig()
        result = config._normalize_base_url("/custom/socket/path")
        
        assert result == "unix:///custom/socket/path"

    def test_get_default_socket_path_windows(self):
        """Test _get_default_socket_path on Windows"""
        with patch('sys.platform', 'win32'):
            config = DockerContainerConfig()
            result = config._get_default_socket_path()
            
            assert result == "//./pipe/docker_engine"

    def test_get_default_socket_path_unix(self):
        """Test _get_default_socket_path on Unix"""
        with patch('sys.platform', 'linux'):
            config = DockerContainerConfig()
            result = config._get_default_socket_path()
            
            assert result == "/var/run/docker.sock"

    def test_get_default_socket_path_darwin(self):
        """Test _get_default_socket_path on macOS"""
        with patch('sys.platform', 'darwin'):
            config = DockerContainerConfig()
            result = config._get_default_socket_path()
            
            assert result == "/var/run/docker.sock"

    def test_validate_always_passes(self):
        """Test validate method always passes (no validation errors)"""
        config = DockerContainerConfig()
        
        # Should not raise any exception
        config.validate()


    def test_base_url_multiple_access(self):
        """Test that base_url can be accessed multiple times"""
        config = DockerContainerConfig()

        url1 = config.base_url
        url2 = config.base_url
        url3 = config.base_url

        assert url1 == url2 == url3

    def test_base_url_uses_default_socket_path(self):
        """Test base_url uses default socket path"""
        config = DockerContainerConfig()
        # Should use default socket path based on platform
        url = config.base_url
        assert url is not None


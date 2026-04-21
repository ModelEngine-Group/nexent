import pytest
from unittest.mock import MagicMock, patch
import json
import os
import tempfile
import shutil

from sdk.nexent.core.utils.observer import MessageObserver, ProcessType
from sdk.nexent.core.tools.read_file_tool import ReadFileTool


@pytest.fixture
def mock_observer():
    """Create a mock observer for testing"""
    observer = MagicMock(spec=MessageObserver)
    observer.lang = "en"
    return observer


@pytest.fixture
def mock_observer_zh():
    """Create a mock observer for testing with Chinese language"""
    observer = MagicMock(spec=MessageObserver)
    observer.lang = "zh"
    return observer


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace directory for testing"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def read_file_tool(mock_observer, temp_workspace):
    """Create ReadFileTool instance for testing"""
    tool = ReadFileTool(
        init_path=temp_workspace,
        observer=mock_observer
    )
    return tool


@pytest.fixture
def read_file_tool_no_observer(temp_workspace):
    """Create ReadFileTool instance without observer for testing"""
    tool = ReadFileTool(
        init_path=temp_workspace,
        observer=None
    )
    return tool


@pytest.fixture
def read_file_tool_zh(mock_observer_zh, temp_workspace):
    """Create ReadFileTool instance with Chinese observer for testing"""
    tool = ReadFileTool(
        init_path=temp_workspace,
        observer=mock_observer_zh
    )
    return tool


class TestReadFileToolInit:
    """Test ReadFileTool initialization"""

    def test_init_with_custom_values(self, mock_observer, temp_workspace):
        """Test initialization with custom values"""
        tool = ReadFileTool(
            init_path=temp_workspace,
            observer=mock_observer
        )

        assert tool.init_path == os.path.abspath(temp_workspace)
        assert tool.observer == mock_observer

    def test_init_with_default_path(self):
        """Test initialization with default path"""
        tool = ReadFileTool(init_path="/mnt/nexent", observer=None)

        assert tool.init_path == os.path.abspath("/mnt/nexent")
        assert tool.observer is None

    def test_init_with_empty_string_raises_error(self):
        """Test initialization with empty string raises ValueError"""
        with pytest.raises(ValueError) as excinfo:
            ReadFileTool(init_path="")

        assert "init_path cannot be empty" in str(excinfo.value)

    def test_init_with_whitespace_only_raises_error(self):
        """Test initialization with whitespace-only string raises ValueError"""
        with pytest.raises(ValueError) as excinfo:
            ReadFileTool(init_path="   ")

        assert "init_path cannot be empty" in str(excinfo.value)


class TestReadFileToolValidatePath:
    """Test _validate_path method"""

    def test_validate_relative_path(self, read_file_tool, temp_workspace):
        """Test validation of relative path"""
        relative_path = "test_dir/file.txt"
        result = read_file_tool._validate_path(relative_path)

        expected_path = os.path.abspath(
            os.path.join(temp_workspace, relative_path))
        assert result == expected_path

    def test_validate_absolute_path_within_workspace(self, read_file_tool, temp_workspace):
        """Test validation of absolute path within workspace"""
        abs_path = os.path.join(temp_workspace, "test_file.txt")
        result = read_file_tool._validate_path(abs_path)

        assert result == os.path.abspath(abs_path)

    def test_validate_absolute_path_outside_workspace(self, read_file_tool):
        """Test validation of absolute path outside workspace"""
        outside_path = "/tmp/outside_workspace.txt"

        with pytest.raises(Exception) as excinfo:
            read_file_tool._validate_path(outside_path)

        assert "Permission denied" in str(excinfo.value)
        assert "outside the allowed area" in str(excinfo.value)

    def test_validate_path_with_dot_components(self, read_file_tool, temp_workspace):
        """Test validation of path with '..' that goes outside workspace"""
        malicious_path = "../../etc/passwd"

        with pytest.raises(Exception) as excinfo:
            read_file_tool._validate_path(malicious_path)

        assert "Permission denied" in str(excinfo.value)

    def test_validate_path_normalization(self, read_file_tool, temp_workspace):
        """Test path normalization"""
        path_with_dots = "test_dir/./subdir/../final.txt"
        result = read_file_tool._validate_path(path_with_dots)

        expected_path = os.path.abspath(
            os.path.join(temp_workspace, "test_dir/final.txt"))
        assert result == expected_path


class TestReadFileToolForward:
    """Test forward method"""

    def test_forward_success_read_file(self, read_file_tool, temp_workspace):
        """Test successful reading of file"""
        file_path = "test_file.txt"
        content = "Hello, World!"
        abs_path = os.path.join(temp_workspace, file_path)

        with open(abs_path, 'w', encoding='utf-8') as f:
            f.write(content)

        result = read_file_tool.forward(file_path)

        result_data = json.loads(result)

        assert result_data["status"] == "success"
        assert result_data["file_path"] == file_path
        assert result_data["absolute_path"] == abs_path
        assert result_data["content"] == content
        assert result_data["content_length"] == len(content)
        assert result_data["file_size_bytes"] == len(content.encode('utf-8'))
        assert result_data["encoding"] == "utf-8"
        assert result_data["lines_count"] == 1
        assert "read successfully" in result_data["message"]

        # Verify observer messages
        read_file_tool.observer.add_message.assert_any_call(
            "", ProcessType.TOOL, "Reading file..."
        )
        read_file_tool.observer.add_message.assert_any_call(
            "", ProcessType.CARD, json.dumps(
                [{"icon": "file-text", "text": f"Reading {file_path}"}], ensure_ascii=False)
        )

    def test_forward_success_multiline_file(self, read_file_tool, temp_workspace):
        """Test successful reading of multiline file"""
        file_path = "multiline.txt"
        content = "Line 1\nLine 2\nLine 3"
        abs_path = os.path.join(temp_workspace, file_path)

        with open(abs_path, 'w', encoding='utf-8') as f:
            f.write(content)

        result = read_file_tool.forward(file_path)

        result_data = json.loads(result)

        assert result_data["content"] == content
        assert result_data["lines_count"] == 3

    def test_forward_success_empty_file(self, read_file_tool, temp_workspace):
        """Test successful reading of empty file"""
        file_path = "empty_file.txt"
        abs_path = os.path.join(temp_workspace, file_path)

        # Create empty file
        with open(abs_path, 'w', encoding='utf-8') as f:
            pass

        result = read_file_tool.forward(file_path)

        result_data = json.loads(result)

        assert result_data["status"] == "success"
        assert result_data["content"] == ""
        assert result_data["content_length"] == 0
        assert result_data["file_size_bytes"] == 0
        assert result_data["lines_count"] == 0  # Empty file has 0 newlines

    def test_forward_success_custom_encoding(self, read_file_tool, temp_workspace):
        """Test successful reading with custom encoding"""
        file_path = "utf16_file.txt"
        content = "Hello, 世界!"
        abs_path = os.path.join(temp_workspace, file_path)

        with open(abs_path, 'w', encoding='utf-16') as f:
            f.write(content)

        result = read_file_tool.forward(file_path, encoding="utf-16")

        result_data = json.loads(result)

        assert result_data["encoding"] == "utf-16"
        assert result_data["content"] == content

    def test_forward_success_large_file_warning(self, read_file_tool, temp_workspace):
        """Test that large file triggers warning"""
        file_path = "large_file.txt"
        abs_path = os.path.join(temp_workspace, file_path)

        # Create a file larger than 10MB
        with open(abs_path, 'w', encoding='utf-8') as f:
            # Write 11MB of content
            f.write("x" * (11 * 1024 * 1024))

        result = read_file_tool.forward(file_path)

        result_data = json.loads(result)

        assert result_data["status"] == "success"
        assert result_data["file_size_bytes"] > 10 * 1024 * 1024

        # Verify warning was sent
        read_file_tool.observer.add_message.assert_any_call(
            "", ProcessType.OTHER, f"Large file warning: {result_data['file_size_bytes']} bytes"
        )

    def test_forward_empty_path(self, read_file_tool):
        """Test forward with empty file path"""
        with pytest.raises(Exception) as excinfo:
            read_file_tool.forward("")

        assert "File path cannot be empty" in str(excinfo.value)

    def test_forward_whitespace_path(self, read_file_tool):
        """Test forward with whitespace-only file path"""
        with pytest.raises(Exception) as excinfo:
            read_file_tool.forward("   ")

        assert "File path cannot be empty" in str(excinfo.value)

    def test_forward_file_not_exists(self, read_file_tool):
        """Test forward when file does not exist"""
        with pytest.raises(Exception) as excinfo:
            read_file_tool.forward("nonexistent_file.txt")

        assert "File does not exist" in str(excinfo.value)

    def test_forward_path_is_directory(self, read_file_tool, temp_workspace):
        """Test forward when path is a directory, not file"""
        dir_path = "test_dir"
        abs_path = os.path.join(temp_workspace, dir_path)

        os.makedirs(abs_path, exist_ok=True)

        with pytest.raises(Exception) as excinfo:
            read_file_tool.forward(dir_path)

        assert "Path is not a file" in str(excinfo.value)

    def test_forward_file_not_exist(self, read_file_tool):
        """Test forward when file does not exist"""
        with pytest.raises(Exception) as excinfo:
            read_file_tool.forward("nonexistent_file.txt")

        assert "File does not exist" in str(excinfo.value)

    def test_forward_permission_error(self, read_file_tool, temp_workspace):
        """Test forward with permission error"""
        file_path = "test_file.txt"
        abs_path = os.path.join(temp_workspace, file_path)

        with open(abs_path, 'w') as f:
            f.write("content")

        with patch('builtins.open', side_effect=PermissionError("Permission denied")):
            with pytest.raises(Exception) as excinfo:
                read_file_tool.forward(file_path)

        assert "Permission denied" in str(excinfo.value)
        assert "Check file permissions" in str(excinfo.value)

    def test_forward_unicode_decode_error(self, read_file_tool, temp_workspace):
        """Test forward with UnicodeDecodeError"""
        file_path = "binary_file.bin"
        abs_path = os.path.join(temp_workspace, file_path)

        # Create binary file
        with open(abs_path, 'wb') as f:
            f.write(b'\x80\x81\x82')

        with pytest.raises(Exception) as excinfo:
            read_file_tool.forward(file_path, encoding="utf-8")

        assert "Encoding error" in str(excinfo.value)
        assert "Try a different encoding" in str(excinfo.value)

    def test_forward_os_error(self, read_file_tool, temp_workspace):
        """Test forward with OS error"""
        file_path = "test_file.txt"
        abs_path = os.path.join(temp_workspace, file_path)

        with open(abs_path, 'w') as f:
            f.write("content")

        with patch('builtins.open', side_effect=OSError("OS error")):
            with pytest.raises(Exception) as excinfo:
                read_file_tool.forward(file_path)

        assert "OS error" in str(excinfo.value)

    def test_forward_unexpected_error(self, read_file_tool, temp_workspace):
        """Test forward with unexpected error"""
        file_path = "test_file.txt"
        abs_path = os.path.join(temp_workspace, file_path)

        with open(abs_path, 'w') as f:
            f.write("content")

        with patch('builtins.open', side_effect=RuntimeError("Unexpected error")):
            with pytest.raises(Exception) as excinfo:
                read_file_tool.forward(file_path)

        assert "Failed to read file" in str(excinfo.value)

    def test_forward_without_observer(self, read_file_tool_no_observer, temp_workspace):
        """Test forward method without observer"""
        file_path = "test_file.txt"
        abs_path = os.path.join(temp_workspace, file_path)
        content = "test content"

        with open(abs_path, 'w') as f:
            f.write(content)

        result = read_file_tool_no_observer.forward(file_path)

        result_data = json.loads(result)

        assert result_data["status"] == "success"
        assert result_data["content"] == content

    def test_forward_chinese_language_observer(self, read_file_tool_zh, temp_workspace):
        """Test forward with Chinese language observer"""
        file_path = "test_file.txt"
        abs_path = os.path.join(temp_workspace, file_path)
        content = "test content"

        with open(abs_path, 'w') as f:
            f.write(content)

        result = read_file_tool_zh.forward(file_path)

        result_data = json.loads(result)

        assert result_data["status"] == "success"

        # Verify Chinese running prompt
        read_file_tool_zh.observer.add_message.assert_any_call(
            "", ProcessType.TOOL, "正在读取文件..."
        )

    def test_forward_chinese_language_large_file_warning(self, read_file_tool_zh, temp_workspace):
        """Test forward with Chinese observer and large file warning"""
        file_path = "large_file.txt"
        abs_path = os.path.join(temp_workspace, file_path)

        # Create a file larger than 10MB
        with open(abs_path, 'w', encoding='utf-8') as f:
            f.write("x" * (11 * 1024 * 1024))

        result = read_file_tool_zh.forward(file_path)

        result_data = json.loads(result)

        assert result_data["status"] == "success"

        # Verify Chinese large file warning
        read_file_tool_zh.observer.add_message.assert_any_call(
            "", ProcessType.OTHER, f"大文件警告: {result_data['file_size_bytes']} 字节"
        )

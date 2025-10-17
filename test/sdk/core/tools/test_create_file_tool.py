import pytest
from unittest.mock import MagicMock, patch
import json
import os
import tempfile
import shutil

# Import target module
from sdk.nexent.core.utils.observer import MessageObserver, ProcessType
from sdk.nexent.core.tools.create_file_tool import CreateFileTool


@pytest.fixture
def mock_observer():
    """Create a mock observer for testing"""
    observer = MagicMock(spec=MessageObserver)
    observer.lang = "en"
    return observer


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace directory for testing"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    # Cleanup after test
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def create_file_tool(mock_observer, temp_workspace):
    """Create CreateFileTool instance for testing"""
    tool = CreateFileTool(
        init_path=temp_workspace,
        observer=mock_observer
    )
    return tool


@pytest.fixture
def create_file_tool_no_observer(temp_workspace):
    """Create CreateFileTool instance without observer for testing"""
    tool = CreateFileTool(
        init_path=temp_workspace,
        observer=None
    )
    return tool


class TestCreateFileTool:
    def test_init_with_custom_values(self, mock_observer, temp_workspace):
        """Test initialization with custom values"""
        tool = CreateFileTool(
            init_path=temp_workspace,
            observer=mock_observer
        )

        assert tool.init_path == os.path.abspath(temp_workspace)
        assert tool.observer == mock_observer

    def test_validate_relative_path(self, create_file_tool, temp_workspace):
        """Test validation of relative path"""
        relative_path = "test_dir/file.txt"
        result = create_file_tool._validate_path(relative_path)

        expected_path = os.path.abspath(
            os.path.join(temp_workspace, relative_path))
        assert result == expected_path

    def test_validate_absolute_path_within_workspace(self, create_file_tool, temp_workspace):
        """Test validation of absolute path within workspace"""
        abs_path = os.path.join(temp_workspace, "test_file.txt")
        result = create_file_tool._validate_path(abs_path)

        assert result == os.path.abspath(abs_path)

    def test_validate_absolute_path_outside_workspace(self, create_file_tool):
        """Test validation of absolute path outside workspace"""
        outside_path = "/tmp/outside_workspace.txt"

        with pytest.raises(Exception) as excinfo:
            create_file_tool._validate_path(outside_path)

        assert "Permission denied" in str(excinfo.value)
        assert "outside the allowed area" in str(excinfo.value)

    def test_validate_path_with_dot_components(self, create_file_tool, temp_workspace):
        """Test validation of path with dot components"""
        # Test with '..' that goes outside workspace
        malicious_path = "../../etc/passwd"

        with pytest.raises(Exception) as excinfo:
            create_file_tool._validate_path(malicious_path)

        assert "Permission denied" in str(excinfo.value)

    def test_validate_path_normalization(self, create_file_tool, temp_workspace):
        """Test path normalization"""
        path_with_dots = "test_dir/./subdir/../final.txt"
        result = create_file_tool._validate_path(path_with_dots)

        expected_path = os.path.abspath(
            os.path.join(temp_workspace, "test_dir/final.txt"))
        assert result == expected_path

    def test_forward_success_new_file(self, create_file_tool, temp_workspace):
        """Test successful creation of new file"""
        file_path = "test_file.txt"
        content = "Hello, World!"

        result = create_file_tool.forward(file_path, content)

        # Parse result
        result_data = json.loads(result)

        # Verify file was created
        abs_path = os.path.join(temp_workspace, file_path)
        assert os.path.exists(abs_path)
        assert os.path.isfile(abs_path)

        # Verify file content
        with open(abs_path, 'r', encoding='utf-8') as f:
            assert f.read() == content

        # Verify result structure
        assert result_data["status"] == "success"
        assert result_data["file_path"] == file_path
        assert result_data["absolute_path"] == abs_path
        assert result_data["content_length"] == len(content)
        assert result_data["file_size_bytes"] == len(content.encode('utf-8'))
        assert result_data["encoding"] == "utf-8"
        assert "created successfully" in result_data["message"]

        # Verify observer messages
        create_file_tool.observer.add_message.assert_any_call(
            "", ProcessType.TOOL, "Creating file..."
        )
        create_file_tool.observer.add_message.assert_any_call(
            "", ProcessType.CARD, json.dumps(
                [{"icon": "file-plus", "text": f"Creating {file_path}"}], ensure_ascii=False)
        )

    def test_forward_success_empty_file(self, create_file_tool, temp_workspace):
        """Test successful creation of empty file"""
        file_path = "empty_file.txt"
        content = ""

        result = create_file_tool.forward(file_path, content)

        # Parse result
        result_data = json.loads(result)

        # Verify file was created
        abs_path = os.path.join(temp_workspace, file_path)
        assert os.path.exists(abs_path)
        assert os.path.isfile(abs_path)

        # Verify file is empty
        assert os.path.getsize(abs_path) == 0

        # Verify result structure
        assert result_data["content_length"] == 0
        assert result_data["file_size_bytes"] == 0

    def test_forward_success_none_content(self, create_file_tool, temp_workspace):
        """Test successful creation with None content"""
        file_path = "none_content.txt"

        result = create_file_tool.forward(file_path, None)

        # Parse result
        result_data = json.loads(result)

        # Verify file was created
        abs_path = os.path.join(temp_workspace, file_path)
        assert os.path.exists(abs_path)
        assert os.path.isfile(abs_path)

        # Verify file is empty
        assert os.path.getsize(abs_path) == 0
        assert result_data["content_length"] == 0

    def test_forward_success_with_custom_encoding(self, create_file_tool, temp_workspace):
        """Test successful creation with custom encoding"""
        file_path = "utf16_file.txt"
        content = "Hello, 世界!"
        encoding = "utf-16"

        result = create_file_tool.forward(file_path, content, encoding)

        # Parse result
        result_data = json.loads(result)

        # Verify encoding
        assert result_data["encoding"] == encoding

        # Verify file was created with correct encoding
        abs_path = os.path.join(temp_workspace, file_path)
        assert os.path.exists(abs_path)

        # Verify file content with correct encoding
        with open(abs_path, 'r', encoding=encoding) as f:
            assert f.read() == content

    def test_forward_success_existing_file_overwrite(self, create_file_tool, temp_workspace):
        """Test successful overwrite of existing file"""
        file_path = "existing_file.txt"
        abs_path = os.path.join(temp_workspace, file_path)

        # Create file first
        with open(abs_path, 'w') as f:
            f.write("old content")

        new_content = "new content"
        result = create_file_tool.forward(file_path, new_content)

        # Parse result
        result_data = json.loads(result)

        # Verify file was overwritten
        with open(abs_path, 'r', encoding='utf-8') as f:
            assert f.read() == new_content

        # Verify observer messages include overwrite warning
        create_file_tool.observer.add_message.assert_any_call(
            "", ProcessType.OTHER, f"File already exists, will overwrite: {abs_path}"
        )

    def test_forward_success_create_parent_directories(self, create_file_tool, temp_workspace):
        """Test successful creation with parent directories"""
        file_path = "deep/nested/path/file.txt"
        content = "test content"

        result = create_file_tool.forward(file_path, content)

        # Parse result
        result_data = json.loads(result)

        # Verify file was created
        abs_path = os.path.join(temp_workspace, file_path)
        assert os.path.exists(abs_path)
        assert os.path.isfile(abs_path)

        # Verify parent directories were created
        parent_dir = os.path.dirname(abs_path)
        assert os.path.exists(parent_dir)
        assert os.path.isdir(parent_dir)

        # Verify file content
        with open(abs_path, 'r', encoding='utf-8') as f:
            assert f.read() == content

    def test_forward_empty_path(self, create_file_tool):
        """Test forward with empty file path"""
        with pytest.raises(Exception) as excinfo:
            create_file_tool.forward("")

        assert "File path cannot be empty" in str(excinfo.value)

    def test_forward_whitespace_path(self, create_file_tool):
        """Test forward with whitespace-only file path"""
        with pytest.raises(Exception) as excinfo:
            create_file_tool.forward("   ")

        assert "File path cannot be empty" in str(excinfo.value)

    def test_forward_permission_error(self, create_file_tool, temp_workspace):
        """Test forward with permission error"""
        file_path = "test_file.txt"

        with patch('builtins.open', side_effect=PermissionError("Permission denied")):
            with pytest.raises(Exception) as excinfo:
                create_file_tool.forward(file_path, "content")

        assert "Permission denied" in str(excinfo.value)
        assert "Check file permissions" in str(excinfo.value)

    def test_forward_unicode_encode_error(self, create_file_tool, temp_workspace):
        """Test forward with Unicode encoding error"""
        file_path = "test_file.txt"
        content = "test content"
        encoding = "ascii"  # This will fail with non-ASCII content

        # Use non-ASCII content to trigger encoding error
        non_ascii_content = "测试内容"

        with pytest.raises(Exception) as excinfo:
            create_file_tool.forward(file_path, non_ascii_content, encoding)

        assert "Encoding error" in str(excinfo.value)
        assert "Try a different encoding" in str(excinfo.value)

    def test_forward_os_error(self, create_file_tool, temp_workspace):
        """Test forward with OS error"""
        file_path = "test_file.txt"

        with patch('builtins.open', side_effect=OSError("OS error")):
            with pytest.raises(Exception) as excinfo:
                create_file_tool.forward(file_path, "content")

        assert "OS error" in str(excinfo.value)

    def test_forward_unexpected_error(self, create_file_tool, temp_workspace):
        """Test forward with unexpected error"""
        file_path = "test_file.txt"

        with patch('builtins.open', side_effect=RuntimeError("Unexpected error")):
            with pytest.raises(Exception) as excinfo:
                create_file_tool.forward(file_path, "content")

        assert "Failed to create file" in str(excinfo.value)

    def test_forward_without_observer(self, create_file_tool_no_observer, temp_workspace):
        """Test forward method without observer"""
        file_path = "test_file.txt"
        content = "test content"

        result = create_file_tool_no_observer.forward(file_path, content)

        # Parse result
        result_data = json.loads(result)

        # Verify file was created
        abs_path = os.path.join(temp_workspace, file_path)
        assert os.path.exists(abs_path)
        assert result_data["status"] == "success"

    def test_forward_chinese_language_observer(self, create_file_tool, temp_workspace):
        """Test forward with Chinese language observer"""
        # Set observer language to Chinese
        create_file_tool.observer.lang = "zh"

        file_path = "test_file.txt"
        content = "test content"

        # Create file first to test overwrite message
        abs_path = os.path.join(temp_workspace, file_path)
        with open(abs_path, 'w') as f:
            f.write("old content")

        result = create_file_tool.forward(file_path, content)

        # Verify Chinese running prompt
        create_file_tool.observer.add_message.assert_any_call(
            "", ProcessType.TOOL, "正在创建文件..."
        )

        # Verify Chinese overwrite warning message
        create_file_tool.observer.add_message.assert_any_call(
            "", ProcessType.OTHER, f"文件已存在，将覆盖: {abs_path}"
        )

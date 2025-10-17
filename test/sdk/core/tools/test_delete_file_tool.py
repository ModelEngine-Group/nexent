import pytest
from unittest.mock import MagicMock, patch
import json
import os
import tempfile
import shutil

# Import target module
from sdk.nexent.core.utils.observer import MessageObserver, ProcessType
from sdk.nexent.core.tools.delete_file_tool import DeleteFileTool


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
def delete_file_tool(mock_observer, temp_workspace):
    """Create DeleteFileTool instance for testing"""
    tool = DeleteFileTool(
        init_path=temp_workspace,
        observer=mock_observer
    )
    return tool


@pytest.fixture
def delete_file_tool_no_observer(temp_workspace):
    """Create DeleteFileTool instance without observer for testing"""
    tool = DeleteFileTool(
        init_path=temp_workspace,
        observer=None
    )
    return tool


class TestDeleteFileTool:
    """Test DeleteFileTool functionality"""

    def test_init_with_custom_values(self, mock_observer, temp_workspace):
        """Test initialization with custom values"""
        tool = DeleteFileTool(
            init_path=temp_workspace,
            observer=mock_observer
        )

        assert tool.init_path == os.path.abspath(temp_workspace)
        assert tool.observer == mock_observer

    def test_validate_relative_path(self, delete_file_tool, temp_workspace):
        """Test validation of relative path"""
        relative_path = "test_dir/file.txt"
        result = delete_file_tool._validate_path(relative_path)

        expected_path = os.path.abspath(
            os.path.join(temp_workspace, relative_path))
        assert result == expected_path

    def test_validate_absolute_path_within_workspace(self, delete_file_tool, temp_workspace):
        """Test validation of absolute path within workspace"""
        abs_path = os.path.join(temp_workspace, "test_file.txt")
        result = delete_file_tool._validate_path(abs_path)

        assert result == os.path.abspath(abs_path)

    def test_validate_absolute_path_outside_workspace(self, delete_file_tool):
        """Test validation of absolute path outside workspace"""
        outside_path = "/tmp/outside_workspace.txt"

        with pytest.raises(Exception) as excinfo:
            delete_file_tool._validate_path(outside_path)

        assert "Permission denied" in str(excinfo.value)
        assert "outside the allowed area" in str(excinfo.value)

    def test_validate_path_with_dot_components(self, delete_file_tool, temp_workspace):
        """Test validation of path with dot components"""
        # Test with '..' that goes outside workspace
        malicious_path = "../../etc/passwd"

        with pytest.raises(Exception) as excinfo:
            delete_file_tool._validate_path(malicious_path)

        assert "Permission denied" in str(excinfo.value)

    def test_validate_path_normalization(self, delete_file_tool, temp_workspace):
        """Test path normalization"""
        path_with_dots = "test_dir/./subdir/../final.txt"
        result = delete_file_tool._validate_path(path_with_dots)

        expected_path = os.path.abspath(
            os.path.join(temp_workspace, "test_dir/final.txt"))
        assert result == expected_path

    def test_forward_success_delete_file(self, delete_file_tool, temp_workspace):
        """Test successful deletion of file"""
        file_path = "test_file.txt"
        abs_path = os.path.join(temp_workspace, file_path)

        # Create file with content
        content = "test content for deletion"
        with open(abs_path, 'w') as f:
            f.write(content)

        result = delete_file_tool.forward(file_path)

        # Parse result
        result_data = json.loads(result)

        # Verify file was deleted
        assert not os.path.exists(abs_path)

        # Verify result structure
        assert result_data["status"] == "success"
        assert result_data["file_path"] == file_path
        assert result_data["absolute_path"] == abs_path
        assert result_data["file_name"] == file_path
        assert result_data["file_size_bytes"] == len(content.encode('utf-8'))
        assert "deleted successfully" in result_data["message"]

        # Verify observer messages
        delete_file_tool.observer.add_message.assert_any_call(
            "", ProcessType.TOOL, "Deleting file..."
        )
        delete_file_tool.observer.add_message.assert_any_call(
            "", ProcessType.CARD, json.dumps(
                [{"icon": "trash", "text": f"Deleting {file_path}"}], ensure_ascii=False)
        )

    def test_forward_success_protected_file_warning(self, delete_file_tool, temp_workspace):
        """Test successful deletion with protected file warning"""
        file_path = "config.env"
        abs_path = os.path.join(temp_workspace, file_path)

        # Create file
        with open(abs_path, 'w') as f:
            f.write("test config")

        result = delete_file_tool.forward(file_path)

        # Parse result
        result_data = json.loads(result)

        # Verify file was deleted
        assert not os.path.exists(abs_path)

        # Verify warning message was sent
        delete_file_tool.observer.add_message.assert_any_call(
            "", ProcessType.OTHER, "Warning: Deleting potentially important file: config.env"
        )

    def test_forward_empty_path(self, delete_file_tool):
        """Test forward with empty file path"""
        with pytest.raises(Exception) as excinfo:
            delete_file_tool.forward("")

        assert "File path cannot be empty" in str(excinfo.value)

    def test_forward_whitespace_path(self, delete_file_tool):
        """Test forward with whitespace-only file path"""
        with pytest.raises(Exception) as excinfo:
            delete_file_tool.forward("   ")

        assert "File path cannot be empty" in str(excinfo.value)

    def test_forward_file_not_exists(self, delete_file_tool):
        """Test forward when file does not exist"""
        with pytest.raises(Exception) as excinfo:
            delete_file_tool.forward("nonexistent_file.txt")

        assert "File does not exist" in str(excinfo.value)

    def test_forward_path_is_directory(self, delete_file_tool, temp_workspace):
        """Test forward when path is a directory, not file"""
        dir_path = "test_dir"
        abs_path = os.path.join(temp_workspace, dir_path)

        # Create a directory instead of file
        os.makedirs(abs_path, exist_ok=True)

        with pytest.raises(Exception) as excinfo:
            delete_file_tool.forward(dir_path)

        assert "Path is not a file" in str(excinfo.value)
        assert "This tool only deletes files, not directories" in str(
            excinfo.value)

    def test_forward_permission_error(self, delete_file_tool, temp_workspace):
        """Test forward with permission error"""
        file_path = "test_file.txt"
        abs_path = os.path.join(temp_workspace, file_path)

        # Create file first
        with open(abs_path, 'w') as f:
            f.write("test content")

        with patch('os.remove', side_effect=PermissionError("Permission denied")):
            with pytest.raises(Exception) as excinfo:
                delete_file_tool.forward(file_path)

        assert "Permission denied" in str(excinfo.value)
        assert "Check file permissions" in str(excinfo.value)

    def test_forward_is_directory_error(self, delete_file_tool, temp_workspace):
        """Test forward with IsADirectoryError"""
        file_path = "test_file.txt"
        abs_path = os.path.join(temp_workspace, file_path)

        # Create file first
        with open(abs_path, 'w') as f:
            f.write("test content")

        with patch('os.remove', side_effect=IsADirectoryError("Is a directory")):
            with pytest.raises(Exception) as excinfo:
                delete_file_tool.forward(file_path)

        assert "Cannot delete directory" in str(excinfo.value)
        assert "This tool only deletes individual files" in str(excinfo.value)

    def test_forward_os_error(self, delete_file_tool, temp_workspace):
        """Test forward with OS error"""
        file_path = "test_file.txt"
        abs_path = os.path.join(temp_workspace, file_path)

        # Create file first
        with open(abs_path, 'w') as f:
            f.write("test content")

        with patch('os.remove', side_effect=OSError("OS error")):
            with pytest.raises(Exception) as excinfo:
                delete_file_tool.forward(file_path)

        assert "OS error" in str(excinfo.value)

    def test_forward_unexpected_error(self, delete_file_tool, temp_workspace):
        """Test forward with unexpected error"""
        file_path = "test_file.txt"
        abs_path = os.path.join(temp_workspace, file_path)

        # Create file first
        with open(abs_path, 'w') as f:
            f.write("test content")

        with patch('os.remove', side_effect=RuntimeError("Unexpected error")):
            with pytest.raises(Exception) as excinfo:
                delete_file_tool.forward(file_path)

        assert "Failed to delete file" in str(excinfo.value)

    def test_forward_without_observer(self, delete_file_tool_no_observer, temp_workspace):
        """Test forward method without observer"""
        file_path = "test_file.txt"
        abs_path = os.path.join(temp_workspace, file_path)

        # Create file first
        with open(abs_path, 'w') as f:
            f.write("test content")

        result = delete_file_tool_no_observer.forward(file_path)

        # Parse result
        result_data = json.loads(result)

        # Verify file was deleted
        assert not os.path.exists(abs_path)
        assert result_data["status"] == "success"

    def test_forward_chinese_language_observer(self, delete_file_tool, temp_workspace):
        """Test forward with Chinese language observer"""
        # Set observer language to Chinese
        delete_file_tool.observer.lang = "zh"

        file_path = "test_file.txt"
        abs_path = os.path.join(temp_workspace, file_path)

        # Create file first
        with open(abs_path, 'w') as f:
            f.write("test content")

        result = delete_file_tool.forward(file_path)

        # Verify Chinese running prompt
        delete_file_tool.observer.add_message.assert_any_call(
            "", ProcessType.TOOL, "正在删除文件..."
        )

        # Verify Chinese warning message for protected file
        protected_file_path = "passwd.txt"
        protected_abs_path = os.path.join(temp_workspace, protected_file_path)
        with open(protected_abs_path, 'w') as f:
            f.write("test content")

        delete_file_tool.forward(protected_file_path)
        delete_file_tool.observer.add_message.assert_any_call(
            "", ProcessType.OTHER, "警告：正在删除可能重要的文件: passwd.txt"
        )

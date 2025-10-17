import pytest
from unittest.mock import MagicMock, patch
import json
import os
import tempfile
import shutil

# Import target module
from sdk.nexent.core.utils.observer import MessageObserver, ProcessType
from sdk.nexent.core.tools.delete_directory_tool import DeleteDirectoryTool


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
def delete_directory_tool(mock_observer, temp_workspace):
    """Create DeleteDirectoryTool instance for testing"""
    tool = DeleteDirectoryTool(
        init_path=temp_workspace,
        observer=mock_observer
    )
    return tool


@pytest.fixture
def delete_directory_tool_no_observer(temp_workspace):
    """Create DeleteDirectoryTool instance without observer for testing"""
    tool = DeleteDirectoryTool(
        init_path=temp_workspace,
        observer=None
    )
    return tool


class TestDeleteDirectoryTool:
    """Test DeleteDirectoryTool functionality"""

    def test_init_with_custom_values(self, mock_observer, temp_workspace):
        """Test initialization with custom values"""
        tool = DeleteDirectoryTool(
            init_path=temp_workspace,
            observer=mock_observer
        )

        assert tool.init_path == os.path.abspath(temp_workspace)
        assert tool.observer == mock_observer

    def test_validate_relative_path(self, delete_directory_tool, temp_workspace):
        """Test validation of relative path"""
        relative_path = "test_dir/subdir"
        result = delete_directory_tool._validate_path(relative_path)

        expected_path = os.path.abspath(
            os.path.join(temp_workspace, relative_path))
        assert result == expected_path

    def test_validate_absolute_path_within_workspace(self, delete_directory_tool, temp_workspace):
        """Test validation of absolute path within workspace"""
        abs_path = os.path.join(temp_workspace, "test_dir")
        result = delete_directory_tool._validate_path(abs_path)

        assert result == os.path.abspath(abs_path)

    def test_validate_absolute_path_outside_workspace(self, delete_directory_tool):
        """Test validation of absolute path outside workspace"""
        outside_path = "/tmp/outside_workspace"

        with pytest.raises(Exception) as excinfo:
            delete_directory_tool._validate_path(outside_path)

        assert "Permission denied" in str(excinfo.value)
        assert "outside the allowed area" in str(excinfo.value)

    def test_validate_path_with_dot_components(self, delete_directory_tool, temp_workspace):
        """Test validation of path with dot components"""
        # Test with '..' that goes outside workspace
        malicious_path = "../../etc/passwd"

        with pytest.raises(Exception) as excinfo:
            delete_directory_tool._validate_path(malicious_path)

        assert "Permission denied" in str(excinfo.value)

    def test_validate_path_normalization(self, delete_directory_tool, temp_workspace):
        """Test path normalization"""
        path_with_dots = "test_dir/./subdir/../final"
        result = delete_directory_tool._validate_path(path_with_dots)

        expected_path = os.path.abspath(
            os.path.join(temp_workspace, "test_dir/final"))
        assert result == expected_path

    def test_validate_path_workspace_root_protection(self, delete_directory_tool, temp_workspace):
        """Test protection against deleting workspace root"""
        with pytest.raises(Exception) as excinfo:
            delete_directory_tool._validate_path(temp_workspace)

        assert "Permission denied" in str(excinfo.value)
        assert "Cannot delete the workspace root directory" in str(
            excinfo.value)

    def test_forward_success_delete_directory(self, delete_directory_tool, temp_workspace):
        """Test successful deletion of directory"""
        directory_path = "test_dir"
        abs_path = os.path.join(temp_workspace, directory_path)

        # Create directory with some files
        os.makedirs(abs_path, exist_ok=True)
        with open(os.path.join(abs_path, "file1.txt"), 'w') as f:
            f.write("test content 1")
        with open(os.path.join(abs_path, "file2.txt"), 'w') as f:
            f.write("test content 2")
        os.makedirs(os.path.join(abs_path, "subdir"), exist_ok=True)

        result = delete_directory_tool.forward(directory_path)

        # Parse result
        result_data = json.loads(result)

        # Verify directory was deleted
        assert not os.path.exists(abs_path)

        # Verify result structure
        assert result_data["status"] == "success"
        assert result_data["directory_path"] == directory_path
        assert result_data["absolute_path"] == abs_path
        assert result_data["directory_name"] == directory_path
        assert result_data["items_deleted"] >= 3  # At least 2 files + 1 subdir
        assert result_data["size_deleted_bytes"] > 0
        assert "deleted successfully" in result_data["message"]

        # Verify observer messages
        delete_directory_tool.observer.add_message.assert_any_call(
            "", ProcessType.TOOL, "Deleting directory..."
        )
        delete_directory_tool.observer.add_message.assert_any_call(
            "", ProcessType.CARD, json.dumps(
                [{"icon": "folder-minus", "text": f"Deleting directory {directory_path}"}], ensure_ascii=False)
        )

    def test_forward_success_large_directory_warning(self, delete_directory_tool, temp_workspace):
        """Test successful deletion with large directory warning"""
        directory_path = "large_dir"
        abs_path = os.path.join(temp_workspace, directory_path)

        # Create directory with many files (>100)
        os.makedirs(abs_path, exist_ok=True)
        for i in range(101):
            with open(os.path.join(abs_path, f"file{i}.txt"), 'w') as f:
                f.write(f"test content {i}")

        result = delete_directory_tool.forward(directory_path)

        # Parse result
        result_data = json.loads(result)

        # Verify directory was deleted
        assert not os.path.exists(abs_path)

        # Verify warning message was sent
        delete_directory_tool.observer.add_message.assert_any_call(
            "", ProcessType.OTHER, "Warning: Deleting large directory with 101 items"
        )

    def test_forward_empty_path(self, delete_directory_tool):
        """Test forward with empty directory path"""
        with pytest.raises(Exception) as excinfo:
            delete_directory_tool.forward("")

        assert "Directory path cannot be empty" in str(excinfo.value)

    def test_forward_whitespace_path(self, delete_directory_tool):
        """Test forward with whitespace-only directory path"""
        with pytest.raises(Exception) as excinfo:
            delete_directory_tool.forward("   ")

        assert "Directory path cannot be empty" in str(excinfo.value)

    def test_forward_directory_not_exists(self, delete_directory_tool):
        """Test forward when directory does not exist"""
        with pytest.raises(Exception) as excinfo:
            delete_directory_tool.forward("nonexistent_dir")

        assert "Directory does not exist" in str(excinfo.value)

    def test_forward_path_is_file(self, delete_directory_tool, temp_workspace):
        """Test forward when path is a file, not directory"""
        file_path = "test_file.txt"
        abs_path = os.path.join(temp_workspace, file_path)

        # Create a file instead of directory
        with open(abs_path, 'w') as f:
            f.write("test content")

        with pytest.raises(Exception) as excinfo:
            delete_directory_tool.forward(file_path)

        assert "Path is not a directory" in str(excinfo.value)
        assert "Use delete_file tool for files" in str(excinfo.value)

    def test_forward_permission_error(self, delete_directory_tool, temp_workspace):
        """Test forward with permission error"""
        directory_path = "test_dir"
        abs_path = os.path.join(temp_workspace, directory_path)

        # Create directory first
        os.makedirs(abs_path, exist_ok=True)

        with patch('shutil.rmtree', side_effect=PermissionError("Permission denied")):
            with pytest.raises(Exception) as excinfo:
                delete_directory_tool.forward(directory_path)

        assert "Permission denied" in str(excinfo.value)
        assert "Check directory permissions" in str(excinfo.value)

    def test_forward_os_error(self, delete_directory_tool, temp_workspace):
        """Test forward with OS error"""
        directory_path = "test_dir"
        abs_path = os.path.join(temp_workspace, directory_path)

        # Create directory first
        os.makedirs(abs_path, exist_ok=True)

        with patch('shutil.rmtree', side_effect=OSError("OS error")):
            with pytest.raises(Exception) as excinfo:
                delete_directory_tool.forward(directory_path)

        assert "OS error" in str(excinfo.value)

    def test_forward_unexpected_error(self, delete_directory_tool, temp_workspace):
        """Test forward with unexpected error"""
        directory_path = "test_dir"
        abs_path = os.path.join(temp_workspace, directory_path)

        # Create directory first
        os.makedirs(abs_path, exist_ok=True)

        with patch('shutil.rmtree', side_effect=RuntimeError("Unexpected error")):
            with pytest.raises(Exception) as excinfo:
                delete_directory_tool.forward(directory_path)

        assert "Failed to delete directory" in str(excinfo.value)

    def test_forward_without_observer(self, delete_directory_tool_no_observer, temp_workspace):
        """Test forward method without observer"""
        directory_path = "test_dir"
        abs_path = os.path.join(temp_workspace, directory_path)

        # Create directory first
        os.makedirs(abs_path, exist_ok=True)

        result = delete_directory_tool_no_observer.forward(directory_path)

        # Parse result
        result_data = json.loads(result)

        # Verify directory was deleted
        assert not os.path.exists(abs_path)
        assert result_data["status"] == "success"

    def test_forward_chinese_language_observer(self, delete_directory_tool, temp_workspace):
        """Test forward with Chinese language observer"""
        # Set observer language to Chinese
        delete_directory_tool.observer.lang = "zh"

        directory_path = "test_dir"
        abs_path = os.path.join(temp_workspace, directory_path)

        # Create directory first
        os.makedirs(abs_path, exist_ok=True)

        result = delete_directory_tool.forward(directory_path)

        # Verify Chinese running prompt
        delete_directory_tool.observer.add_message.assert_any_call(
            "", ProcessType.TOOL, "正在删除文件夹..."
        )

        # Verify Chinese warning message for large directory
        # Create another large directory
        large_dir_path = "large_dir"
        large_abs_path = os.path.join(temp_workspace, large_dir_path)
        os.makedirs(large_abs_path, exist_ok=True)
        for i in range(101):
            with open(os.path.join(large_abs_path, f"file{i}.txt"), 'w') as f:
                f.write(f"test content {i}")

        delete_directory_tool.forward(large_dir_path)
        delete_directory_tool.observer.add_message.assert_any_call(
            "", ProcessType.OTHER, "警告：正在删除包含 101 个项目的大文件夹"
        )

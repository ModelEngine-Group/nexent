import pytest
from unittest.mock import MagicMock, patch
import json
import os
import tempfile
import shutil

# Import target module
from sdk.nexent.core.utils.observer import MessageObserver, ProcessType
from sdk.nexent.core.tools.create_directory_tool import CreateDirectoryTool


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
def create_directory_tool(mock_observer, temp_workspace):
    """Create CreateDirectoryTool instance for testing"""
    tool = CreateDirectoryTool(
        init_path=temp_workspace,
        observer=mock_observer
    )
    return tool


@pytest.fixture
def create_directory_tool_no_observer(temp_workspace):
    """Create CreateDirectoryTool instance without observer for testing"""
    tool = CreateDirectoryTool(
        init_path=temp_workspace,
        observer=None
    )
    return tool


class TestCreateDirectoryTool:
    """Test CreateDirectoryTool functionality"""

    def test_init_with_custom_values(self, mock_observer, temp_workspace):
        """Test initialization with custom values"""
        tool = CreateDirectoryTool(
            init_path=temp_workspace,
            observer=mock_observer
        )

        assert tool.init_path == os.path.abspath(temp_workspace)
        assert tool.observer == mock_observer

    def test_validate_relative_path(self, create_directory_tool, temp_workspace):
        """Test validation of relative path"""
        relative_path = "test_dir/subdir"
        result = create_directory_tool._validate_path(relative_path)

        expected_path = os.path.abspath(
            os.path.join(temp_workspace, relative_path))
        assert result == expected_path

    def test_validate_absolute_path_within_workspace(self, create_directory_tool, temp_workspace):
        """Test validation of absolute path within workspace"""
        abs_path = os.path.join(temp_workspace, "test_dir")
        result = create_directory_tool._validate_path(abs_path)

        assert result == os.path.abspath(abs_path)

    def test_validate_absolute_path_outside_workspace(self, create_directory_tool):
        """Test validation of absolute path outside workspace"""
        outside_path = "/tmp/outside_workspace"

        with pytest.raises(Exception) as excinfo:
            create_directory_tool._validate_path(outside_path)

        assert "Permission denied" in str(excinfo.value)
        assert "outside the allowed area" in str(excinfo.value)

    def test_validate_path_with_dot_components(self, create_directory_tool, temp_workspace):
        """Test validation of path with dot components"""
        # Test with '..' that goes outside workspace
        malicious_path = "../../etc/passwd"

        with pytest.raises(Exception) as excinfo:
            create_directory_tool._validate_path(malicious_path)

        assert "Permission denied" in str(excinfo.value)

    def test_validate_path_normalization(self, create_directory_tool, temp_workspace):
        """Test path normalization"""
        path_with_dots = "test_dir/./subdir/../final"
        result = create_directory_tool._validate_path(path_with_dots)

        expected_path = os.path.abspath(
            os.path.join(temp_workspace, "test_dir/final"))
        assert result == expected_path

    def test_forward_success_new_directory(self, create_directory_tool, temp_workspace):
        """Test successful creation of new directory"""
        directory_path = "test_dir"

        result = create_directory_tool.forward(directory_path)

        # Parse result
        result_data = json.loads(result)

        # Verify directory was created
        abs_path = os.path.join(temp_workspace, directory_path)
        assert os.path.exists(abs_path)
        assert os.path.isdir(abs_path)

        # Verify result structure
        assert result_data["status"] == "success"
        assert result_data["directory_path"] == directory_path
        assert result_data["absolute_path"] == abs_path
        assert result_data["permissions"] == "755"
        assert result_data["already_existed"] is False
        assert "created successfully" in result_data["message"]

        # Verify observer messages
        create_directory_tool.observer.add_message.assert_any_call(
            "", ProcessType.TOOL, "Creating directory..."
        )
        create_directory_tool.observer.add_message.assert_any_call(
            "", ProcessType.CARD, json.dumps(
                [{"icon": "folder-plus", "text": f"Creating directory {directory_path}"}], ensure_ascii=False)
        )

    def test_forward_success_existing_directory(self, create_directory_tool, temp_workspace):
        """Test successful handling of existing directory"""
        directory_path = "existing_dir"
        abs_path = os.path.join(temp_workspace, directory_path)

        # Create directory first
        os.makedirs(abs_path, exist_ok=True)

        result = create_directory_tool.forward(directory_path)

        # Parse result
        result_data = json.loads(result)

        # Verify result structure
        assert result_data["status"] == "success"
        assert result_data["already_existed"] is True
        assert "verified" in result_data["message"]

        # Verify observer messages include existing directory message
        create_directory_tool.observer.add_message.assert_any_call(
            "", ProcessType.OTHER, f"Directory already exists: {directory_path}"
        )

    def test_forward_success_with_custom_permissions(self, create_directory_tool, temp_workspace):
        """Test successful creation with custom permissions"""
        directory_path = "test_dir"
        permissions = "644"

        result = create_directory_tool.forward(directory_path, permissions)

        # Parse result
        result_data = json.loads(result)

        # Verify permissions
        assert result_data["permissions"] == permissions

        # Verify directory was created with correct permissions
        abs_path = os.path.join(temp_workspace, directory_path)
        assert os.path.exists(abs_path)

    def test_forward_empty_path(self, create_directory_tool):
        """Test forward with empty directory path"""
        with pytest.raises(Exception) as excinfo:
            create_directory_tool.forward("")

        assert "Directory path cannot be empty" in str(excinfo.value)

    def test_forward_whitespace_path(self, create_directory_tool):
        """Test forward with whitespace-only directory path"""
        with pytest.raises(Exception) as excinfo:
            create_directory_tool.forward("   ")

        assert "Directory path cannot be empty" in str(excinfo.value)

    def test_forward_invalid_permissions(self, create_directory_tool):
        """Test forward with invalid permissions format"""
        with pytest.raises(Exception) as excinfo:
            create_directory_tool.forward("test_dir", "invalid")

        assert "Invalid permissions format" in str(excinfo.value)
        assert "octal format" in str(excinfo.value)

    def test_forward_path_exists_as_file(self, create_directory_tool, temp_workspace):
        """Test forward when path exists as file"""
        directory_path = "existing_file"
        abs_path = os.path.join(temp_workspace, directory_path)

        # Create a file instead of directory
        with open(abs_path, 'w') as f:
            f.write("test content")

        with pytest.raises(Exception) as excinfo:
            create_directory_tool.forward(directory_path)

        assert "Path already exists but is not a directory" in str(
            excinfo.value)

    def test_forward_permission_error(self, create_directory_tool, temp_workspace):
        """Test forward with permission error"""
        directory_path = "test_dir"

        with patch('os.makedirs', side_effect=PermissionError("Permission denied")):
            with pytest.raises(Exception) as excinfo:
                create_directory_tool.forward(directory_path)

        assert "Permission denied" in str(excinfo.value)
        assert "Check directory permissions" in str(excinfo.value)

    def test_forward_os_error(self, create_directory_tool, temp_workspace):
        """Test forward with OS error"""
        directory_path = "test_dir"

        with patch('os.makedirs', side_effect=OSError("OS error")):
            with pytest.raises(Exception) as excinfo:
                create_directory_tool.forward(directory_path)

        assert "OS error" in str(excinfo.value)

    def test_forward_unexpected_error(self, create_directory_tool, temp_workspace):
        """Test forward with unexpected error"""
        directory_path = "test_dir"

        with patch('os.makedirs', side_effect=RuntimeError("Unexpected error")):
            with pytest.raises(Exception) as excinfo:
                create_directory_tool.forward(directory_path)

        assert "Failed to create directory" in str(excinfo.value)

    def test_forward_without_observer(self, create_directory_tool_no_observer, temp_workspace):
        """Test forward method without observer"""
        directory_path = "test_dir"

        result = create_directory_tool_no_observer.forward(directory_path)

        # Parse result
        result_data = json.loads(result)

        # Verify directory was created
        abs_path = os.path.join(temp_workspace, directory_path)
        assert os.path.exists(abs_path)
        assert result_data["status"] == "success"

    def test_forward_chinese_language_observer(self, create_directory_tool, temp_workspace):
        """Test forward with Chinese language observer"""
        # Set observer language to Chinese
        create_directory_tool.observer.lang = "zh"

        directory_path = "test_dir"
        result = create_directory_tool.forward(directory_path)

        # Verify Chinese running prompt
        create_directory_tool.observer.add_message.assert_any_call(
            "", ProcessType.TOOL, "正在创建文件夹..."
        )

        # Verify Chinese existing directory message
        # Call again to trigger existing directory message
        create_directory_tool.forward("test_dir")
        create_directory_tool.observer.add_message.assert_any_call(
            "", ProcessType.OTHER, f"目录已存在: test_dir"
        )

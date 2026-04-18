import pytest
from unittest.mock import MagicMock, patch
import json
import os
import tempfile
import shutil

from sdk.nexent.core.utils.observer import MessageObserver, ProcessType
from sdk.nexent.core.tools.move_item_tool import MoveItemTool


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
def move_item_tool(mock_observer, temp_workspace):
    """Create MoveItemTool instance for testing"""
    tool = MoveItemTool(
        init_path=temp_workspace,
        observer=mock_observer
    )
    return tool


@pytest.fixture
def move_item_tool_no_observer(temp_workspace):
    """Create MoveItemTool instance without observer for testing"""
    tool = MoveItemTool(
        init_path=temp_workspace,
        observer=None
    )
    return tool


@pytest.fixture
def move_item_tool_zh(mock_observer_zh, temp_workspace):
    """Create MoveItemTool instance with Chinese observer for testing"""
    tool = MoveItemTool(
        init_path=temp_workspace,
        observer=mock_observer_zh
    )
    return tool


class TestMoveItemToolInit:
    """Test MoveItemTool initialization"""

    def test_init_with_custom_values(self, mock_observer, temp_workspace):
        """Test initialization with custom values"""
        tool = MoveItemTool(
            init_path=temp_workspace,
            observer=mock_observer
        )

        assert tool.init_path == os.path.abspath(temp_workspace)
        assert tool.observer == mock_observer

    def test_init_with_default_path(self):
        """Test initialization with default path"""
        tool = MoveItemTool(init_path="/mnt/nexent", observer=None)

        assert tool.init_path == os.path.abspath("/mnt/nexent")
        assert tool.observer is None

    def test_init_with_empty_string_raises_error(self):
        """Test initialization with empty string raises ValueError"""
        with pytest.raises(ValueError) as excinfo:
            MoveItemTool(init_path="")

        assert "init_path cannot be empty" in str(excinfo.value)

    def test_init_with_whitespace_only_raises_error(self):
        """Test initialization with whitespace-only string raises ValueError"""
        with pytest.raises(ValueError) as excinfo:
            MoveItemTool(init_path="   ")

        assert "init_path cannot be empty" in str(excinfo.value)


class TestMoveItemToolValidatePath:
    """Test _validate_path method"""

    def test_validate_relative_path(self, move_item_tool, temp_workspace):
        """Test validation of relative path"""
        relative_path = "test_dir/file.txt"
        result = move_item_tool._validate_path(relative_path)

        expected_path = os.path.abspath(
            os.path.join(temp_workspace, relative_path))
        assert result == expected_path

    def test_validate_absolute_path_within_workspace(self, move_item_tool, temp_workspace):
        """Test validation of absolute path within workspace"""
        abs_path = os.path.join(temp_workspace, "test_file.txt")
        result = move_item_tool._validate_path(abs_path)

        assert result == os.path.abspath(abs_path)

    def test_validate_absolute_path_outside_workspace(self, move_item_tool):
        """Test validation of absolute path outside workspace"""
        outside_path = "/tmp/outside_workspace.txt"

        with pytest.raises(Exception) as excinfo:
            move_item_tool._validate_path(outside_path)

        assert "Permission denied" in str(excinfo.value)
        assert "outside the allowed area" in str(excinfo.value)

    def test_validate_path_with_dot_components(self, move_item_tool, temp_workspace):
        """Test validation of path with '..' that goes outside workspace"""
        malicious_path = "../../etc/passwd"

        with pytest.raises(Exception) as excinfo:
            move_item_tool._validate_path(malicious_path)

        assert "Permission denied" in str(excinfo.value)

    def test_validate_path_normalization(self, move_item_tool, temp_workspace):
        """Test path normalization"""
        path_with_dots = "test_dir/./subdir/../final.txt"
        result = move_item_tool._validate_path(path_with_dots)

        expected_path = os.path.abspath(
            os.path.join(temp_workspace, "test_dir/final.txt"))
        assert result == expected_path


class TestMoveItemToolForward:
    """Test forward method"""

    def test_forward_success_move_file(self, move_item_tool, temp_workspace):
        """Test successful moving of a file"""
        source_path = "source_file.txt"
        dest_path = "dest_file.txt"
        source_abs = os.path.join(temp_workspace, source_path)
        dest_abs = os.path.join(temp_workspace, dest_path)
        content = "test content for moving"

        with open(source_abs, 'w', encoding='utf-8') as f:
            f.write(content)

        result = move_item_tool.forward(source_path, dest_path)

        result_data = json.loads(result)

        # Verify file was moved
        assert not os.path.exists(source_abs)
        assert os.path.exists(dest_abs)

        # Verify result structure
        assert result_data["status"] == "success"
        assert result_data["source_path"] == source_path
        assert result_data["destination_path"] == dest_path
        assert result_data["absolute_source_path"] == source_abs
        assert result_data["absolute_destination_path"] == dest_abs
        assert result_data["item_name"] == source_path
        assert result_data["is_directory"] is False
        assert result_data["items_moved"] == 1
        assert result_data["message"] == f"File moved successfully from {source_path} to {dest_path}"

        # Verify observer messages
        move_item_tool.observer.add_message.assert_any_call(
            "", ProcessType.TOOL, "Moving file/directory..."
        )
        move_item_tool.observer.add_message.assert_any_call(
            "", ProcessType.CARD, json.dumps(
                [{"icon": "move", "text": f"Moving {source_path} to {dest_path}"}], ensure_ascii=False)
        )

    def test_forward_success_move_file_to_subdirectory(self, move_item_tool, temp_workspace):
        """Test successful moving of a file to a new subdirectory"""
        source_path = "file.txt"
        dest_path = "subdir/moved_file.txt"
        source_abs = os.path.join(temp_workspace, source_path)
        dest_abs = os.path.join(temp_workspace, dest_path)

        with open(source_abs, 'w') as f:
            f.write("content")

        result = move_item_tool.forward(source_path, dest_path)

        result_data = json.loads(result)

        assert not os.path.exists(source_abs)
        assert os.path.exists(dest_abs)
        assert result_data["status"] == "success"

    def test_forward_success_move_file_creates_parent_directories(self, move_item_tool, temp_workspace):
        """Test that moving file creates parent directories if needed"""
        source_path = "source.txt"
        dest_path = "deep/nested/path/dest.txt"
        source_abs = os.path.join(temp_workspace, source_path)

        with open(source_abs, 'w') as f:
            f.write("content")

        result = move_item_tool.forward(source_path, dest_path)

        result_data = json.loads(result)

        assert result_data["status"] == "success"
        assert os.path.exists(os.path.join(temp_workspace, "deep/nested/path"))

    def test_forward_success_move_directory(self, move_item_tool, temp_workspace):
        """Test successful moving of a directory"""
        source_path = "source_dir"
        dest_path = "dest_dir"
        source_abs = os.path.join(temp_workspace, source_path)
        dest_abs = os.path.join(temp_workspace, dest_path)

        os.makedirs(source_abs)
        with open(os.path.join(source_abs, "file1.txt"), 'w') as f:
            f.write("content1")
        with open(os.path.join(source_abs, "file2.txt"), 'w') as f:
            f.write("content2")

        result = move_item_tool.forward(source_path, dest_path)

        result_data = json.loads(result)

        # Verify directory was moved
        assert not os.path.exists(source_abs)
        assert os.path.exists(dest_abs)
        assert os.path.isdir(dest_abs)

        # Verify nested files
        assert os.path.exists(os.path.join(dest_abs, "file1.txt"))
        assert os.path.exists(os.path.join(dest_abs, "file2.txt"))

        # Verify result
        assert result_data["status"] == "success"
        assert result_data["is_directory"] is True
        assert result_data["items_moved"] == 3  # 2 files + 1 directory

    def test_forward_success_directory_with_nested_structure(self, move_item_tool, temp_workspace):
        """Test moving directory with nested structure"""
        source_path = "source_nested"
        dest_path = "dest_nested"
        source_abs = os.path.join(temp_workspace, source_path)

        # Create nested structure
        nested_dir = os.path.join(source_abs, "level1", "level2")
        os.makedirs(nested_dir)
        with open(os.path.join(nested_dir, "deep_file.txt"), 'w') as f:
            f.write("deep content")

        result = move_item_tool.forward(source_path, dest_path)

        result_data = json.loads(result)

        assert result_data["status"] == "success"
        assert result_data["is_directory"] is True
        assert os.path.exists(os.path.join(temp_workspace, dest_path, "level1", "level2", "deep_file.txt"))

    def test_forward_empty_source_path(self, move_item_tool):
        """Test forward with empty source path"""
        with pytest.raises(Exception) as excinfo:
            move_item_tool.forward("", "dest.txt")

        assert "Source path cannot be empty" in str(excinfo.value)

    def test_forward_whitespace_source_path(self, move_item_tool):
        """Test forward with whitespace-only source path"""
        with pytest.raises(Exception) as excinfo:
            move_item_tool.forward("   ", "dest.txt")

        assert "Source path cannot be empty" in str(excinfo.value)

    def test_forward_empty_destination_path(self, move_item_tool):
        """Test forward with empty destination path"""
        with pytest.raises(Exception) as excinfo:
            move_item_tool.forward("source.txt", "")

        assert "Destination path cannot be empty" in str(excinfo.value)

    def test_forward_whitespace_destination_path(self, move_item_tool):
        """Test forward with whitespace-only destination path"""
        with pytest.raises(Exception) as excinfo:
            move_item_tool.forward("source.txt", "   ")

        assert "Destination path cannot be empty" in str(excinfo.value)

    def test_forward_source_not_exists(self, move_item_tool):
        """Test forward when source does not exist"""
        with pytest.raises(Exception) as excinfo:
            move_item_tool.forward("nonexistent.txt", "dest.txt")

        assert "Source does not exist" in str(excinfo.value)

    def test_forward_destination_already_exists(self, move_item_tool, temp_workspace):
        """Test forward when destination already exists"""
        source_path = "source.txt"
        dest_path = "existing.txt"
        source_abs = os.path.join(temp_workspace, source_path)
        dest_abs = os.path.join(temp_workspace, dest_path)

        with open(source_abs, 'w') as f:
            f.write("source content")
        with open(dest_abs, 'w') as f:
            f.write("existing content")

        with pytest.raises(Exception) as excinfo:
            move_item_tool.forward(source_path, dest_path)

        assert "Destination already exists" in str(excinfo.value)
        assert "Move operation cancelled" in str(excinfo.value)

        # Verify source still exists
        assert os.path.exists(source_abs)

    def test_forward_file_not_found_error(self, move_item_tool, temp_workspace):
        """Test forward with FileNotFoundError during move"""
        source_path = "source.txt"
        dest_path = "dest.txt"
        source_abs = os.path.join(temp_workspace, source_path)

        with open(source_abs, 'w') as f:
            f.write("content")

        with patch('shutil.move', side_effect=FileNotFoundError("File not found")):
            with pytest.raises(Exception) as excinfo:
                move_item_tool.forward(source_path, dest_path)

        assert "Source not found" in str(excinfo.value)

    def test_forward_permission_error(self, move_item_tool, temp_workspace):
        """Test forward with permission error"""
        source_path = "source.txt"
        dest_path = "dest.txt"
        source_abs = os.path.join(temp_workspace, source_path)

        with open(source_abs, 'w') as f:
            f.write("content")

        with patch('shutil.move', side_effect=PermissionError("Permission denied")):
            with pytest.raises(Exception) as excinfo:
                move_item_tool.forward(source_path, dest_path)

        assert "Permission denied" in str(excinfo.value)
        assert "Check file/directory permissions" in str(excinfo.value)

    def test_forward_os_error(self, move_item_tool, temp_workspace):
        """Test forward with OS error"""
        source_path = "source.txt"
        dest_path = "dest.txt"
        source_abs = os.path.join(temp_workspace, source_path)

        with open(source_abs, 'w') as f:
            f.write("content")

        with patch('shutil.move', side_effect=OSError("OS error")):
            with pytest.raises(Exception) as excinfo:
                move_item_tool.forward(source_path, dest_path)

        assert "OS error" in str(excinfo.value)

    def test_forward_unexpected_error(self, move_item_tool, temp_workspace):
        """Test forward with unexpected error"""
        source_path = "source.txt"
        dest_path = "dest.txt"
        source_abs = os.path.join(temp_workspace, source_path)

        with open(source_abs, 'w') as f:
            f.write("content")

        with patch('shutil.move', side_effect=RuntimeError("Unexpected error")):
            with pytest.raises(Exception) as excinfo:
                move_item_tool.forward(source_path, dest_path)

        assert "Failed to move item" in str(excinfo.value)

    def test_forward_without_observer(self, move_item_tool_no_observer, temp_workspace):
        """Test forward method without observer"""
        source_path = "source.txt"
        dest_path = "dest.txt"
        source_abs = os.path.join(temp_workspace, source_path)
        dest_abs = os.path.join(temp_workspace, dest_path)

        with open(source_abs, 'w') as f:
            f.write("content")

        result = move_item_tool_no_observer.forward(source_path, dest_path)

        result_data = json.loads(result)

        assert not os.path.exists(source_abs)
        assert os.path.exists(dest_abs)
        assert result_data["status"] == "success"

    def test_forward_chinese_language_observer(self, move_item_tool_zh, temp_workspace):
        """Test forward with Chinese language observer"""
        source_path = "source.txt"
        dest_path = "dest.txt"
        source_abs = os.path.join(temp_workspace, source_path)

        with open(source_abs, 'w') as f:
            f.write("content")

        result = move_item_tool_zh.forward(source_path, dest_path)

        result_data = json.loads(result)

        assert result_data["status"] == "success"

        # Verify Chinese running prompt
        move_item_tool_zh.observer.add_message.assert_any_call(
            "", ProcessType.TOOL, "正在移动文件/文件夹..."
        )

        # Verify Chinese card content
        move_item_tool_zh.observer.add_message.assert_any_call(
            "", ProcessType.CARD, json.dumps(
                [{"icon": "move", "text": f"Moving {source_path} to {dest_path}"}], ensure_ascii=False)
        )

    def test_forward_moved_file_size(self, move_item_tool, temp_workspace):
        """Test that file size is correctly reported"""
        source_path = "source.txt"
        dest_path = "dest.txt"
        source_abs = os.path.join(temp_workspace, source_path)
        content = "test content"

        with open(source_abs, 'w') as f:
            f.write(content)

        result = move_item_tool.forward(source_path, dest_path)

        result_data = json.loads(result)

        assert result_data["size_bytes"] == len(content.encode('utf-8'))

    def test_forward_destination_parent_creation(self, move_item_tool, temp_workspace):
        """Test that destination parent directory is created"""
        source_path = "source.txt"
        dest_path = "new_parent/dest.txt"
        source_abs = os.path.join(temp_workspace, source_path)

        with open(source_abs, 'w') as f:
            f.write("content")

        result = move_item_tool.forward(source_path, dest_path)

        result_data = json.loads(result)

        assert result_data["status"] == "success"
        assert os.path.exists(os.path.join(temp_workspace, "new_parent"))

    def test_forward_moving_directory_to_existing_file_fails(self, move_item_tool, temp_workspace):
        """Test that moving directory fails if destination is existing file"""
        source_path = "source_dir"
        dest_path = "existing_file.txt"
        source_abs = os.path.join(temp_workspace, source_path)
        dest_abs = os.path.join(temp_workspace, dest_path)

        os.makedirs(source_abs)
        with open(dest_abs, 'w') as f:
            f.write("existing content")

        with pytest.raises(Exception) as excinfo:
            move_item_tool.forward(source_path, dest_path)

        assert "Destination already exists" in str(excinfo.value)

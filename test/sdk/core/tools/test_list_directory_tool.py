import pytest
from unittest.mock import MagicMock, patch
import json
import os
import tempfile
import shutil

from sdk.nexent.core.utils.observer import MessageObserver, ProcessType
from sdk.nexent.core.tools.list_directory_tool import ListDirectoryTool


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
def list_directory_tool(mock_observer, temp_workspace):
    """Create ListDirectoryTool instance for testing"""
    tool = ListDirectoryTool(
        init_path=temp_workspace,
        observer=mock_observer
    )
    return tool


@pytest.fixture
def list_directory_tool_no_observer(temp_workspace):
    """Create ListDirectoryTool instance without observer for testing"""
    tool = ListDirectoryTool(
        init_path=temp_workspace,
        observer=None
    )
    return tool


@pytest.fixture
def list_directory_tool_zh(mock_observer_zh, temp_workspace):
    """Create ListDirectoryTool instance with Chinese observer for testing"""
    tool = ListDirectoryTool(
        init_path=temp_workspace,
        observer=mock_observer_zh
    )
    return tool


class TestListDirectoryToolInit:
    """Test ListDirectoryTool initialization"""

    def test_init_with_custom_values(self, mock_observer, temp_workspace):
        """Test initialization with custom values"""
        tool = ListDirectoryTool(
            init_path=temp_workspace,
            observer=mock_observer
        )

        assert tool.init_path == os.path.abspath(temp_workspace)
        assert tool.observer == mock_observer

    def test_init_with_default_path(self):
        """Test initialization with default path"""
        tool = ListDirectoryTool(init_path="/mnt/nexent", observer=None)

        assert tool.init_path == os.path.abspath("/mnt/nexent")
        assert tool.observer is None

    def test_init_with_empty_string_raises_error(self):
        """Test initialization with empty string raises ValueError"""
        with pytest.raises(ValueError) as excinfo:
            ListDirectoryTool(init_path="")

        assert "init_path cannot be empty" in str(excinfo.value)

    def test_init_with_whitespace_only_raises_error(self):
        """Test initialization with whitespace-only string raises ValueError"""
        with pytest.raises(ValueError) as excinfo:
            ListDirectoryTool(init_path="   ")

        assert "init_path cannot be empty" in str(excinfo.value)


class TestListDirectoryToolValidatePath:
    """Test _validate_path method"""

    def test_validate_current_directory(self, list_directory_tool, temp_workspace):
        """Test validation of current directory marker '.'"""
        result = list_directory_tool._validate_path(".")
        assert result == list_directory_tool.init_path

    def test_validate_empty_path(self, list_directory_tool, temp_workspace):
        """Test validation of empty path returns init_path"""
        result = list_directory_tool._validate_path("")
        assert result == list_directory_tool.init_path

    def test_validate_relative_path(self, list_directory_tool, temp_workspace):
        """Test validation of relative path"""
        relative_path = "test_dir/file.txt"
        result = list_directory_tool._validate_path(relative_path)

        expected_path = os.path.abspath(
            os.path.join(temp_workspace, relative_path))
        assert result == expected_path

    def test_validate_absolute_path_within_workspace(self, list_directory_tool, temp_workspace):
        """Test validation of absolute path within workspace"""
        abs_path = os.path.join(temp_workspace, "test_file.txt")
        result = list_directory_tool._validate_path(abs_path)

        assert result == os.path.abspath(abs_path)

    def test_validate_absolute_path_outside_workspace(self, list_directory_tool):
        """Test validation of absolute path outside workspace"""
        outside_path = "/tmp/outside_workspace.txt"

        with pytest.raises(Exception) as excinfo:
            list_directory_tool._validate_path(outside_path)

        assert "Permission denied" in str(excinfo.value)
        assert "outside the allowed area" in str(excinfo.value)

    def test_validate_path_with_dot_components(self, list_directory_tool, temp_workspace):
        """Test validation of path with '..' that goes outside workspace"""
        malicious_path = "../../etc/passwd"

        with pytest.raises(Exception) as excinfo:
            list_directory_tool._validate_path(malicious_path)

        assert "Permission denied" in str(excinfo.value)

    def test_validate_path_normalization(self, list_directory_tool, temp_workspace):
        """Test path normalization"""
        path_with_dots = "test_dir/./subdir/../final.txt"
        result = list_directory_tool._validate_path(path_with_dots)

        expected_path = os.path.abspath(
            os.path.join(temp_workspace, "test_dir/final.txt"))
        assert result == expected_path


class TestListDirectoryToolFormatSize:
    """Test _format_size method"""

    def test_format_size_bytes(self, list_directory_tool):
        """Test formatting bytes"""
        result = list_directory_tool._format_size(512)
        assert result == "512B"

    def test_format_size_kilobytes(self, list_directory_tool):
        """Test formatting kilobytes"""
        result = list_directory_tool._format_size(2048)
        assert result == "2.0KB"

    def test_format_size_megabytes(self, list_directory_tool):
        """Test formatting megabytes"""
        result = list_directory_tool._format_size(1024 * 1024 * 5)
        assert result == "5.0MB"

    def test_format_size_gigabytes(self, list_directory_tool):
        """Test formatting gigabytes"""
        result = list_directory_tool._format_size(1024 * 1024 * 1024 * 2)
        assert result == "2.0GB"


class TestListDirectoryToolBuildTreeStructure:
    """Test _build_tree_structure method"""

    def test_build_tree_structure_empty_directory(self, list_directory_tool, temp_workspace):
        """Test building tree structure for empty directory"""
        result = list_directory_tool._build_tree_structure(
            temp_workspace, max_depth=3, show_hidden=False, show_size=True
        )

        assert "children" in result
        assert result["children"] == []

    def test_build_tree_structure_with_files(self, list_directory_tool, temp_workspace):
        """Test building tree structure with files"""
        # Create test files
        file1 = os.path.join(temp_workspace, "file1.txt")
        file2 = os.path.join(temp_workspace, "file2.txt")
        with open(file1, 'w') as f:
            f.write("content1")
        with open(file2, 'w') as f:
            f.write("content2")

        result = list_directory_tool._build_tree_structure(
            temp_workspace, max_depth=3, show_hidden=False, show_size=True
        )

        assert "children" in result
        assert len(result["children"]) == 2

        names = [item["name"] for item in result["children"]]
        assert "file1.txt" in names
        assert "file2.txt" in names

    def test_build_tree_structure_with_subdirectories(self, list_directory_tool, temp_workspace):
        """Test building tree structure with subdirectories"""
        subdir = os.path.join(temp_workspace, "subdir")
        os.makedirs(subdir)

        file1 = os.path.join(subdir, "nested_file.txt")
        with open(file1, 'w') as f:
            f.write("nested content")

        result = list_directory_tool._build_tree_structure(
            temp_workspace, max_depth=3, show_hidden=False, show_size=True
        )

        assert "children" in result
        dir_item = next((item for item in result["children"] if item["name"] == "subdir"), None)
        assert dir_item is not None
        assert dir_item["type"] == "directory"
        assert "children" in dir_item

    def test_build_tree_structure_max_depth_reached(self, list_directory_tool, temp_workspace):
        """Test that max_depth limits recursion"""
        subdir = os.path.join(temp_workspace, "level1")
        nested_subdir = os.path.join(subdir, "level2")
        os.makedirs(nested_subdir, exist_ok=True)

        with open(os.path.join(subdir, "file.txt"), 'w') as f:
            f.write("content")
        with open(os.path.join(nested_subdir, "nested_file.txt"), 'w') as f:
            f.write("content")

        result = list_directory_tool._build_tree_structure(
            temp_workspace, max_depth=1, show_hidden=False, show_size=True
        )

        assert "children" in result
        dir_item = next((item for item in result["children"] if item["type"] == "directory"), None)
        assert dir_item is not None
        assert dir_item.get("truncated") is True

    def test_build_tree_structure_show_hidden(self, list_directory_tool, temp_workspace):
        """Test building tree structure with hidden files"""
        # Create normal and hidden files
        normal_file = os.path.join(temp_workspace, "normal.txt")
        hidden_file = os.path.join(temp_workspace, ".hidden")
        with open(normal_file, 'w') as f:
            f.write("normal")
        with open(hidden_file, 'w') as f:
            f.write("hidden")

        # Without show_hidden
        result = list_directory_tool._build_tree_structure(
            temp_workspace, max_depth=3, show_hidden=False, show_size=True
        )
        names = [item["name"] for item in result["children"]]
        assert "normal.txt" in names
        assert ".hidden" not in names

        # With show_hidden
        result = list_directory_tool._build_tree_structure(
            temp_workspace, max_depth=3, show_hidden=True, show_size=True
        )
        names = [item["name"] for item in result["children"]]
        assert "normal.txt" in names
        assert ".hidden" in names

    def test_build_tree_structure_permission_error(self, list_directory_tool, temp_workspace):
        """Test handling permission error when reading directory"""
        with patch('os.listdir', side_effect=PermissionError("Permission denied")):
            result = list_directory_tool._build_tree_structure(
                temp_workspace, max_depth=3, show_hidden=False, show_size=True
            )
            assert "error" in result
            assert "Permission denied" in result["error"]

    def test_build_tree_structure_os_error(self, list_directory_tool, temp_workspace):
        """Test handling OS error when reading directory"""
        with patch('os.listdir', side_effect=OSError("OS error")):
            result = list_directory_tool._build_tree_structure(
                temp_workspace, max_depth=3, show_hidden=False, show_size=True
            )
            assert "error" in result

    def test_build_tree_structure_item_count(self, list_directory_tool, temp_workspace):
        """Test that item_count is set for directories"""
        subdir = os.path.join(temp_workspace, "testdir")
        os.makedirs(subdir)

        # Create files in subdir
        for i in range(3):
            with open(os.path.join(subdir, f"file{i}.txt"), 'w') as f:
                f.write("content")

        result = list_directory_tool._build_tree_structure(
            temp_workspace, max_depth=3, show_hidden=False, show_size=True
        )

        dir_item = next((item for item in result["children"] if item["name"] == "testdir"), None)
        assert dir_item is not None
        assert dir_item["item_count"] == 3

    def test_build_tree_structure_show_size(self, list_directory_tool, temp_workspace):
        """Test that file sizes are included when show_size is True"""
        file1 = os.path.join(temp_workspace, "small.txt")
        with open(file1, 'w') as f:
            f.write("small")

        result = list_directory_tool._build_tree_structure(
            temp_workspace, max_depth=3, show_hidden=False, show_size=True
        )

        file_item = next((item for item in result["children"] if item["name"] == "small.txt"), None)
        assert file_item is not None
        assert "size" in file_item
        assert "size_formatted" in file_item

        # Without show_size
        result = list_directory_tool._build_tree_structure(
            temp_workspace, max_depth=3, show_hidden=False, show_size=False
        )

        file_item = next((item for item in result["children"] if item["name"] == "small.txt"), None)
        assert file_item is not None
        assert "size" not in file_item


class TestListDirectoryToolFormatTreeDisplay:
    """Test _format_tree_display method"""

    def test_format_tree_display_empty(self, list_directory_tool):
        """Test formatting empty tree"""
        result = list_directory_tool._format_tree_display(
            {"children": []}, show_size=True
        )
        assert result == []

    def test_format_tree_display_with_files(self, list_directory_tool):
        """Test formatting tree with files"""
        tree_data = {
            "children": [
                {"name": "file1.txt", "type": "file", "size_formatted": "100B"},
                {"name": "file2.txt", "type": "file", "size_formatted": "200B"}
            ]
        }

        result = list_directory_tool._format_tree_display(tree_data, show_size=True)

        assert len(result) == 2
        assert "file1.txt" in result[0]
        assert "100B" in result[0]
        assert "file2.txt" in result[1]
        assert "200B" in result[1]

    def test_format_tree_display_with_directories(self, list_directory_tool):
        """Test formatting tree with directories"""
        tree_data = {
            "children": [
                {
                    "name": "subdir",
                    "type": "directory",
                    "item_count": 5,
                    "children": [
                        {"name": "nested.txt", "type": "file"}
                    ]
                }
            ]
        }

        result = list_directory_tool._format_tree_display(tree_data, show_size=True)

        assert len(result) == 2
        assert "subdir/" in result[0]
        assert "5 items" in result[0]
        assert "nested.txt" in result[1]

    def test_format_tree_display_truncated_directory(self, list_directory_tool):
        """Test formatting truncated directory"""
        tree_data = {
            "children": [
                {
                    "name": "deepdir",
                    "type": "directory",
                    "truncated": True,
                    "children": []
                }
            ]
        }

        result = list_directory_tool._format_tree_display(tree_data, show_size=True)

        assert "deepdir/" in result[0]
        assert "[...]" in result[0]

    def test_format_tree_display_with_errors(self, list_directory_tool):
        """Test formatting tree with error entries"""
        tree_data = {
            "children": [
                {"name": "error_file", "type": "unknown", "error": "Access denied"}
            ]
        }

        result = list_directory_tool._format_tree_display(tree_data, show_size=True)

        assert len(result) == 1
        assert "error_file" in result[0]
        assert "[ERROR: Access denied]" in result[0]

    def test_format_tree_display_nested_recursion(self, list_directory_tool):
        """Test that nested recursion works correctly"""
        tree_data = {
            "children": [
                {
                    "name": "parent",
                    "type": "directory",
                    "children": [
                        {
                            "name": "child",
                            "type": "directory",
                            "children": [
                                {"name": "grandchild.txt", "type": "file"}
                            ]
                        }
                    ]
                }
            ]
        }

        result = list_directory_tool._format_tree_display(tree_data, show_size=True)

        assert len(result) == 3
        assert any("parent/" in line for line in result)
        assert any("child/" in line for line in result)
        assert any("grandchild.txt" in line for line in result)


class TestListDirectoryToolForward:
    """Test forward method"""

    def test_forward_success_empty_directory(self, list_directory_tool, temp_workspace):
        """Test successful listing of empty directory"""
        result = list_directory_tool.forward(".")

        result_data = json.loads(result)

        assert result_data["status"] == "success"
        assert result_data["directory_path"] == "."
        assert "tree_display" in result_data
        assert "tree_data" in result_data
        assert "summary" in result_data
        assert result_data["summary"]["total_files"] == 0
        assert result_data["summary"]["total_directories"] == 0

    def test_forward_success_with_files(self, list_directory_tool, temp_workspace):
        """Test successful listing with files"""
        # Create test structure
        file1 = os.path.join(temp_workspace, "file1.txt")
        file2 = os.path.join(temp_workspace, "file2.txt")
        with open(file1, 'w') as f:
            f.write("Hello")
        with open(file2, 'w') as f:
            f.write("World")

        result = list_directory_tool.forward(".")

        result_data = json.loads(result)

        assert result_data["status"] == "success"
        assert result_data["summary"]["total_files"] == 2
        assert result_data["summary"]["total_directories"] == 0

    def test_forward_success_with_subdirectories(self, list_directory_tool, temp_workspace):
        """Test successful listing with subdirectories"""
        subdir = os.path.join(temp_workspace, "subdir")
        os.makedirs(subdir)

        with open(os.path.join(subdir, "nested.txt"), 'w') as f:
            f.write("content")

        result = list_directory_tool.forward(".", max_depth=3)

        result_data = json.loads(result)

        assert result_data["status"] == "success"
        assert result_data["summary"]["total_directories"] >= 1

    def test_forward_none_directory_path(self, list_directory_tool, temp_workspace):
        """Test forward with None directory_path defaults to '.'"""
        result = list_directory_tool.forward(directory_path=None)

        result_data = json.loads(result)

        assert result_data["status"] == "success"

    def test_forward_max_depth_limit(self, list_directory_tool, temp_workspace):
        """Test that max_depth is limited to 10"""
        result = list_directory_tool.forward(".", max_depth=15)

        result_data = json.loads(result)

        assert result_data["summary"]["max_depth"] == 10

    def test_forward_min_depth_limit(self, list_directory_tool, temp_workspace):
        """Test that max_depth minimum is 1"""
        result = list_directory_tool.forward(".", max_depth=0)

        result_data = json.loads(result)

        assert result_data["summary"]["max_depth"] == 1

    def test_forward_directory_not_exist(self, list_directory_tool):
        """Test forward when directory does not exist"""
        with pytest.raises(Exception) as excinfo:
            list_directory_tool.forward("nonexistent_directory")

        assert "Directory does not exist" in str(excinfo.value)

    def test_forward_path_is_file_not_directory(self, list_directory_tool, temp_workspace):
        """Test forward when path is a file, not directory"""
        file_path = os.path.join(temp_workspace, "afile.txt")
        with open(file_path, 'w') as f:
            f.write("content")

        with pytest.raises(Exception) as excinfo:
            list_directory_tool.forward("afile.txt")

        assert "Path is not a directory" in str(excinfo.value)

    def test_forward_permission_error(self, list_directory_tool, temp_workspace):
        """Test forward with permission error"""
        with patch('os.listdir', side_effect=PermissionError("Permission denied")):
            with pytest.raises(Exception) as excinfo:
                list_directory_tool.forward(".")

        assert "Permission denied" in str(excinfo.value)

    def test_forward_os_error(self, list_directory_tool, temp_workspace):
        """Test forward with OS error"""
        with patch('os.listdir', side_effect=OSError("OS error")):
            with pytest.raises(Exception) as excinfo:
                list_directory_tool.forward(".")

        assert "OS error" in str(excinfo.value)

    def test_forward_unexpected_error(self, list_directory_tool, temp_workspace):
        """Test forward with unexpected error"""
        with patch('os.listdir', side_effect=RuntimeError("Unexpected error")):
            with pytest.raises(Exception) as excinfo:
                list_directory_tool.forward(".")

        assert "Failed to list directory" in str(excinfo.value)

    def test_forward_without_observer(self, list_directory_tool_no_observer, temp_workspace):
        """Test forward method without observer"""
        file_path = os.path.join(temp_workspace, "test_file.txt")
        with open(file_path, 'w') as f:
            f.write("content")

        result = list_directory_tool_no_observer.forward(".")

        result_data = json.loads(result)

        assert result_data["status"] == "success"

    def test_forward_chinese_language_observer(self, list_directory_tool_zh, temp_workspace):
        """Test forward with Chinese language observer"""
        file_path = os.path.join(temp_workspace, "test_file.txt")
        with open(file_path, 'w') as f:
            f.write("content")

        result = list_directory_tool_zh.forward(".")

        result_data = json.loads(result)

        assert result_data["status"] == "success"

        # Verify Chinese running prompt was sent
        list_directory_tool_zh.observer.add_message.assert_any_call(
            "", ProcessType.TOOL, "正在列出目录内容..."
        )

        # Verify Chinese card content
        list_directory_tool_zh.observer.add_message.assert_any_call(
            "", ProcessType.CARD, json.dumps(
                [{"icon": "folder-tree", "text": "Listing directory ."}], ensure_ascii=False)
        )

    def test_forward_show_hidden_files(self, list_directory_tool, temp_workspace):
        """Test forward with show_hidden enabled"""
        # Create hidden and normal files
        normal_file = os.path.join(temp_workspace, "normal.txt")
        hidden_file = os.path.join(temp_workspace, ".hidden")
        with open(normal_file, 'w') as f:
            f.write("normal")
        with open(hidden_file, 'w') as f:
            f.write("hidden")

        result = list_directory_tool.forward(".", show_hidden=True)

        result_data = json.loads(result)

        assert result_data["summary"]["show_hidden"] is True
        assert result_data["summary"]["total_files"] == 2

    def test_forward_show_size_disabled(self, list_directory_tool, temp_workspace):
        """Test forward with show_size disabled"""
        file_path = os.path.join(temp_workspace, "file.txt")
        with open(file_path, 'w') as f:
            f.write("content")

        result = list_directory_tool.forward(".", show_size=False)

        result_data = json.loads(result)

        assert result_data["status"] == "success"
        assert result_data["summary"]["total_size_bytes"] == 0

    def test_forward_relative_subdirectory(self, list_directory_tool, temp_workspace):
        """Test forward with relative subdirectory path"""
        subdir = os.path.join(temp_workspace, "subdir")
        os.makedirs(subdir)

        with open(os.path.join(subdir, "nested.txt"), 'w') as f:
            f.write("content")

        result = list_directory_tool.forward("subdir")

        result_data = json.loads(result)

        assert result_data["status"] == "success"
        assert result_data["directory_path"] == "subdir"

import pytest
from unittest.mock import MagicMock
import json
import os
import tempfile
import shutil

from sdk.nexent.core.utils.observer import MessageObserver
from sdk.nexent.core.tools.download_from_s3_tool import DownloadFromS3Tool
from sdk.nexent.core.tools.upload_to_s3_tool import UploadToS3Tool


@pytest.fixture
def mock_observer():
    observer = MagicMock(spec=MessageObserver)
    observer.lang = "en"
    return observer


@pytest.fixture
def mock_minio_client():
    client = MagicMock()
    client.default_bucket = "nexent-bucket"
    client.get_file_size.return_value = 1024
    client.download_file.return_value = (True, "Downloaded successfully")
    client.upload_file.return_value = (True, "/nexent-bucket/workspace/u1/outputs/test.txt")
    client.get_file_url.return_value = (True, "https://minio.example.com/presigned-url")
    return client


@pytest.fixture
def temp_workspace():
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


# ======================================================================
# DownloadFromS3Tool Tests
# ======================================================================

class TestDownloadFromS3ToolInit:
    def test_init_defaults(self):
        tool = DownloadFromS3Tool()
        assert tool.workspace_path == os.path.abspath("/mnt/nexent")
        assert tool.minio_client is None
        assert tool.user_id == ""

    def test_init_custom(self, mock_observer, mock_minio_client, temp_workspace):
        tool = DownloadFromS3Tool(
            workspace_path=temp_workspace,
            minio_client=mock_minio_client,
            user_id="user1",
            tenant_id="tenant1",
            observer=mock_observer,
        )
        assert tool.workspace_path == os.path.abspath(temp_workspace)
        assert tool.user_id == "user1"
        assert tool.tenant_id == "tenant1"


class TestDownloadFromS3ToolParsePath:
    def test_parse_s3_url(self):
        bucket, key = DownloadFromS3Tool._parse_s3_path("s3://mybucket/path/to/file.pdf")
        assert bucket == "mybucket"
        assert key == "path/to/file.pdf"

    def test_parse_single_slash_s3_url(self):
        bucket, key = DownloadFromS3Tool._parse_s3_path("s3:/mybucket/path/to/file.pdf")
        assert bucket == "mybucket"
        assert key == "path/to/file.pdf"

    def test_parse_slash_path(self):
        bucket, key = DownloadFromS3Tool._parse_s3_path("/mybucket/path/to/file.pdf")
        assert bucket == "mybucket"
        assert key == "path/to/file.pdf"

    def test_parse_plain_key(self):
        bucket, key = DownloadFromS3Tool._parse_s3_path("attachments/user1/file.pdf")
        assert bucket is None
        assert key == "attachments/user1/file.pdf"

    def test_parse_empty_raises(self):
        with pytest.raises(ValueError):
            DownloadFromS3Tool._parse_s3_path("")

    def test_parse_invalid_format(self):
        with pytest.raises(ValueError):
            DownloadFromS3Tool._parse_s3_path("s3://")


class TestDownloadFromS3ToolAccessControl:
    @pytest.fixture
    def tool(self, temp_workspace):
        return DownloadFromS3Tool(
            workspace_path=temp_workspace,
            user_id="user1",
            tenant_id="tenant1",
        )

    def test_knowledge_base_allowed(self, tool):
        assert tool._check_access("knowledge_base/doc.pdf") is True

    def test_images_in_attachments_allowed(self, tool):
        assert tool._check_access("images_in_attachments/img.png") is True

    def test_own_attachments_allowed(self, tool):
        assert tool._check_access("attachments/user1/report.pdf") is True

    def test_other_attachments_denied(self, tool):
        assert tool._check_access("attachments/user2/secret.pdf") is False

    def test_own_skill_files_allowed(self, tool):
        assert tool._check_access("skill-files/user1/doc.pdf") is True

    def test_other_skill_files_denied(self, tool):
        assert tool._check_access("skill-files/user2/doc.pdf") is False

    def test_own_workspace_allowed(self, tool):
        assert tool._check_access("workspace/user1/run1/outputs/file.pdf") is True

    def test_other_workspace_denied(self, tool):
        assert tool._check_access("workspace/user2/run1/outputs/file.pdf") is False
        assert tool._check_access("workspace/tenant1/user1/run1/outputs/file.pdf") is False

    def test_arbitrary_object_key_denied(self, tool):
        assert tool._check_access("private/user1/secret.txt") is False

    def test_asset_owner_attachment_denied_without_backend_validator(self, tool):
        assert tool._check_access("attachments/asset_owner/secret.txt") is False

    def test_legacy_flat_attachment_allowed(self, tool):
        assert tool._check_access("attachments/legacy.txt") is True

    def test_no_user_id_denied(self, temp_workspace):
        tool = DownloadFromS3Tool(workspace_path=temp_workspace, user_id="")
        assert tool._check_access("knowledge_base/doc.pdf") is False


class TestDownloadFromS3ToolForward:
    @pytest.fixture
    def tool(self, mock_observer, mock_minio_client, temp_workspace):
        return DownloadFromS3Tool(
            workspace_path=temp_workspace,
            minio_client=mock_minio_client,
            user_id="user1",
            tenant_id="tenant1",
            observer=mock_observer,
        )

    def test_download_success(self, tool, temp_workspace, mock_minio_client):
        result = tool.forward("s3://nexent-bucket/attachments/user1/report.pdf")
        data = json.loads(result)
        assert data["status"] == "success"
        assert "report.pdf" in data["local_path"]
        assert data["file_size_bytes"] == 1024
        mock_minio_client.download_file.assert_called_once()

    def test_download_with_custom_filename(self, tool, mock_minio_client):
        result = tool.forward("s3://nexent-bucket/attachments/user1/report.pdf", "my_report.pdf")
        data = json.loads(result)
        assert data["status"] == "success"
        assert "my_report.pdf" in data["local_path"]

    def test_download_notifies_completion_callback(
        self, mock_observer, mock_minio_client, temp_workspace
    ):
        callback = MagicMock()
        tool = DownloadFromS3Tool(
            workspace_path=temp_workspace,
            minio_client=mock_minio_client,
            user_id="user1",
            tenant_id="tenant1",
            observer=mock_observer,
            on_download=callback,
        )

        result = json.loads(tool.forward("attachments/user1/report.pdf"))

        callback.assert_called_once_with(result)

    def test_download_empty_path_raises(self, tool):
        with pytest.raises(Exception, match="cannot be empty"):
            tool.forward("")

    def test_download_invalid_s3_path_uses_value_error_mapping(self, tool):
        with pytest.raises(Exception, match="Invalid S3 path"):
            tool.forward("s3://missing-object-key")

    def test_download_object_key_without_filename_raises(self, tool):
        with pytest.raises(Exception, match="Cannot determine filename"):
            tool.forward("attachments/user1/")

    def test_download_no_minio_client_raises(self, temp_workspace):
        tool = DownloadFromS3Tool(workspace_path=temp_workspace, user_id="user1")
        with pytest.raises(Exception, match="MinIO client is not configured"):
            tool.forward("s3://bucket/key")

    def test_download_permission_denied_raises(self, tool):
        with pytest.raises(Exception, match="Permission denied"):
            tool.forward("s3://nexent-bucket/attachments/user2/secret.pdf")

    def test_download_file_too_large_raises(self, tool, mock_minio_client):
        mock_minio_client.get_file_size.return_value = 200 * 1024 * 1024
        with pytest.raises(Exception, match="too large"):
            tool.forward("s3://nexent-bucket/attachments/user1/huge.pdf")

    def test_download_file_not_found_raises(self, tool, mock_minio_client):
        mock_minio_client.get_file_size.return_value = 0
        with pytest.raises(Exception, match="not found"):
            tool.forward("s3://nexent-bucket/attachments/user1/missing.pdf")

    def test_download_minio_failure_raises(self, tool, mock_minio_client):
        mock_minio_client.download_file.return_value = (False, "Network error")
        with pytest.raises(Exception, match="Failed to download"):
            tool.forward("s3://nexent-bucket/attachments/user1/report.pdf")

    def test_download_plain_key(self, tool, mock_minio_client):
        result = tool.forward("attachments/user1/data.csv")
        data = json.loads(result)
        assert data["status"] == "success"
        mock_minio_client.download_file.assert_called_once_with(
            "attachments/user1/data.csv",
            os.path.join(tool.workspace_path, "data.csv"),
            None,
        )

    def test_download_plain_key_uses_canonical_path_for_backend_validator(
        self, mock_minio_client, temp_workspace
    ):
        validator = MagicMock()
        tool = DownloadFromS3Tool(
            workspace_path=temp_workspace,
            minio_client=mock_minio_client,
            user_id="user1",
            tenant_id="tenant1",
            validate_url_access=validator,
        )

        tool.forward("attachments/user1/data.csv")

        validator.assert_called_once_with([
            "s3://nexent-bucket/attachments/user1/data.csv"
        ])

    def test_download_rejects_sibling_workspace_prefix(self, tool, temp_workspace):
        sibling = os.path.basename(temp_workspace) + "-other/file.txt"
        with pytest.raises(Exception, match="outside the workspace"):
            tool.forward("attachments/user1/data.csv", f"../{sibling}")


# ======================================================================
# UploadToS3Tool Tests
# ======================================================================

class TestUploadToS3ToolInit:
    def test_init_defaults(self):
        tool = UploadToS3Tool()
        assert tool.workspace_path == os.path.abspath("/mnt/nexent")
        assert tool.minio_client is None
        assert tool.user_id == ""

    def test_init_custom(self, mock_observer, mock_minio_client, temp_workspace):
        shared_uploaded_paths = set()
        tool = UploadToS3Tool(
            workspace_path=temp_workspace,
            minio_client=mock_minio_client,
            user_id="user1",
            tenant_id="tenant1",
            observer=mock_observer,
            uploaded_paths=shared_uploaded_paths,
        )
        assert tool.workspace_path == os.path.abspath(temp_workspace)
        assert tool.user_id == "user1"
        assert tool.uploaded_paths is shared_uploaded_paths


class TestUploadToS3ToolPathValidation:
    @pytest.fixture
    def tool(self, temp_workspace):
        return UploadToS3Tool(
            workspace_path=temp_workspace,
            user_id="user1",
            tenant_id="tenant1",
            run_id="run1",
        )

    def test_validate_relative_path(self, tool, temp_workspace):
        abs_path = tool._validate_path("outputs/report.pdf")
        assert abs_path == os.path.normpath(os.path.join(temp_workspace, "outputs/report.pdf"))

    def test_validate_absolute_path_within_workspace(self, tool, temp_workspace):
        abs_input = os.path.join(temp_workspace, "outputs", "report.pdf")
        result = tool._validate_path(abs_input)
        assert result == os.path.normpath(abs_input)

    def test_validate_path_outside_workspace_raises(self, tool):
        with pytest.raises(Exception, match="Permission denied"):
            tool._validate_path("../../etc/passwd")

    def test_bare_upload_path_candidates_prefer_outputs(self, tool, temp_workspace):
        candidates = tool._upload_path_candidates("reports/report.pdf")

        assert candidates == [
            os.path.normpath(
                os.path.join(temp_workspace, "outputs", "reports", "report.pdf")
            ),
            os.path.normpath(os.path.join(temp_workspace, "reports", "report.pdf")),
        ]

    def test_outputs_prefixed_candidate_is_not_duplicated(self, tool, temp_workspace):
        candidates = tool._upload_path_candidates("outputs/report.pdf")

        assert candidates == [
            os.path.normpath(os.path.join(temp_workspace, "outputs", "report.pdf"))
        ]

    def test_absolute_upload_path_has_single_candidate(self, tool, temp_workspace):
        absolute_path = os.path.join(temp_workspace, "outputs", "report.pdf")

        assert tool._upload_path_candidates(absolute_path) == [
            os.path.normpath(absolute_path)
        ]

    def test_build_s3_key(self, tool):
        key = tool._build_s3_key("report.pdf")
        assert key == "workspace/user1/run1/outputs/report.pdf"

    def test_build_s3_key_preserves_nested_output_path(self, tool):
        key = tool._build_s3_key("outputs/charts/report.pdf")
        assert key == "workspace/user1/run1/outputs/charts/report.pdf"

    def test_build_s3_key_requires_run_id(self, temp_workspace):
        tool = UploadToS3Tool(workspace_path=temp_workspace, user_id="user1")

        with pytest.raises(ValueError, match="run IDs are required"):
            tool._build_s3_key("report.pdf")

    @pytest.mark.parametrize("target_name", ["/absolute.txt", "../escape.txt"])
    def test_build_s3_key_rejects_unsafe_target(self, tool, target_name):
        with pytest.raises(ValueError, match="output prefix"):
            tool._build_s3_key(target_name)

    def test_build_s3_key_rejects_empty_target(self, tool):
        with pytest.raises(ValueError, match="cannot be empty"):
            tool._build_s3_key(".")

    @pytest.mark.parametrize(
        ("user_id", "run_id"),
        [("user/child", "run1"), ("user1", "run\\child")],
    )
    def test_build_s3_key_rejects_multi_segment_identity(
        self, temp_workspace, user_id, run_id
    ):
        tool = UploadToS3Tool(
            workspace_path=temp_workspace,
            user_id=user_id,
            run_id=run_id,
        )

        with pytest.raises(ValueError, match="single path segments"):
            tool._build_s3_key("report.pdf")


class TestUploadToS3ToolForward:
    @pytest.fixture
    def tool_with_file(self, mock_observer, mock_minio_client, temp_workspace):
        """Create tool and a test file in workspace."""
        tool = UploadToS3Tool(
            workspace_path=temp_workspace,
            minio_client=mock_minio_client,
            user_id="user1",
            tenant_id="tenant1",
            run_id="run1",
            observer=mock_observer,
        )
        # Create a test file
        test_file = os.path.join(temp_workspace, "test_report.txt")
        with open(test_file, "w") as f:
            f.write("Hello, world!")
        return tool, test_file

    def test_upload_success(self, tool_with_file, mock_minio_client):
        tool, test_file = tool_with_file
        result = tool.forward("test_report.txt")
        data = json.loads(result)
        assert data["status"] == "success"
        assert "s3://" in data["s3_url"]
        assert data["url"] == data["s3_url"]
        assert "presigned_url" not in data
        assert data["file_size_bytes"] == len("Hello, world!")
        mock_minio_client.upload_file.assert_called_once()
        mock_minio_client.get_file_url.assert_not_called()

    def test_upload_with_target_filename(self, tool_with_file, mock_minio_client):
        tool, test_file = tool_with_file
        result = tool.forward("test_report.txt", "custom_name.txt")
        data = json.loads(result)
        assert data["status"] == "success"
        assert "custom_name.txt" in data["s3_url"]

    def test_upload_bare_relative_path_falls_back_to_outputs(
        self, mock_minio_client, temp_workspace
    ):
        output_dir = os.path.join(temp_workspace, "outputs")
        os.makedirs(output_dir)
        output_file = os.path.join(output_dir, "test.txt")
        with open(output_file, "w", encoding="utf-8") as file_obj:
            file_obj.write("generated in sandbox cwd")
        tool = UploadToS3Tool(
            workspace_path=temp_workspace,
            minio_client=mock_minio_client,
            user_id="user1",
            run_id="run1",
        )

        data = json.loads(tool.forward("test.txt"))

        assert data["local_path"] == os.path.join("outputs", "test.txt")
        mock_minio_client.upload_file.assert_called_once_with(
            output_file,
            "workspace/user1/run1/outputs/test.txt",
        )

    def test_upload_bare_relative_path_prefers_outputs_over_workspace_root(
        self, mock_minio_client, temp_workspace
    ):
        output_dir = os.path.join(temp_workspace, "outputs")
        os.makedirs(output_dir)
        output_file = os.path.join(output_dir, "result.txt")
        root_file = os.path.join(temp_workspace, "result.txt")
        with open(output_file, "w", encoding="utf-8") as file_obj:
            file_obj.write("generated output")
        with open(root_file, "w", encoding="utf-8") as file_obj:
            file_obj.write("unrelated workspace file")
        tool = UploadToS3Tool(
            workspace_path=temp_workspace,
            minio_client=mock_minio_client,
            user_id="user1",
            run_id="run1",
        )

        data = json.loads(tool.forward("result.txt"))

        assert data["local_path"] == os.path.join("outputs", "result.txt")
        mock_minio_client.upload_file.assert_called_once_with(
            output_file,
            "workspace/user1/run1/outputs/result.txt",
        )

    def test_upload_includes_run_id_and_notifies_callback(
        self, mock_minio_client, temp_workspace
    ):
        callback = MagicMock()
        test_file = os.path.join(temp_workspace, "result.txt")
        with open(test_file, "w", encoding="utf-8") as file_obj:
            file_obj.write("result")
        tool = UploadToS3Tool(
            workspace_path=temp_workspace,
            minio_client=mock_minio_client,
            user_id="user1",
            tenant_id="tenant1",
            run_id="run-123",
            on_upload=callback,
        )

        data = json.loads(tool.forward("result.txt"))

        assert data["object_name"] == "workspace/user1/run-123/outputs/result.txt"
        assert data["name"] == "result.txt"
        callback.assert_called_once_with(data)

    def test_upload_updates_shared_uploaded_path_registry(
        self, mock_minio_client, temp_workspace
    ):
        shared_uploaded_paths = set()
        test_file = os.path.join(temp_workspace, "result.txt")
        with open(test_file, "w", encoding="utf-8") as file_obj:
            file_obj.write("result")
        tool = UploadToS3Tool(
            workspace_path=temp_workspace,
            minio_client=mock_minio_client,
            user_id="user1",
            run_id="run-123",
            uploaded_paths=shared_uploaded_paths,
        )

        tool.forward("result.txt")

        assert os.path.normcase(os.path.abspath(test_file)) in shared_uploaded_paths

    def test_upload_empty_path_raises(self, tool_with_file):
        tool, _ = tool_with_file
        with pytest.raises(Exception, match="cannot be empty"):
            tool.forward("")

    def test_upload_no_minio_client_raises(self, temp_workspace):
        tool = UploadToS3Tool(workspace_path=temp_workspace, user_id="user1")
        with pytest.raises(Exception, match="MinIO client is not configured"):
            tool.forward("file.txt")

    def test_upload_no_user_id_raises(self, temp_workspace, mock_minio_client):
        tool = UploadToS3Tool(workspace_path=temp_workspace, minio_client=mock_minio_client, user_id="")
        with pytest.raises(Exception, match="User authentication required"):
            tool.forward("file.txt")

    def test_upload_nonexistent_file_raises(self, tool_with_file):
        tool, _ = tool_with_file
        with pytest.raises(Exception, match="does not exist"):
            tool.forward("nonexistent.txt")

    def test_upload_uses_local_file_callback_before_existence_check(
        self, mock_minio_client, temp_workspace
    ):
        callback = MagicMock()
        target_path = os.path.join(temp_workspace, "generated.txt")

        def create_file(_path):
            with open(target_path, "w", encoding="utf-8") as file_obj:
                file_obj.write("generated")

        callback.side_effect = create_file
        tool = UploadToS3Tool(
            workspace_path=temp_workspace,
            minio_client=mock_minio_client,
            user_id="user1",
            run_id="run1",
            ensure_local_file=callback,
        )

        result = json.loads(tool.forward("generated.txt"))

        callback.assert_called_once_with(
            os.path.join(temp_workspace, "outputs", "generated.txt")
        )
        assert result["status"] == "success"

    def test_upload_directory_raises(self, mock_minio_client, temp_workspace):
        directory = os.path.join(temp_workspace, "folder")
        os.makedirs(directory)
        tool = UploadToS3Tool(
            workspace_path=temp_workspace,
            minio_client=mock_minio_client,
            user_id="user1",
            run_id="run1",
        )

        with pytest.raises(Exception, match="not a regular file"):
            tool.forward("folder")

    def test_upload_path_outside_workspace_raises(self, tool_with_file):
        tool, _ = tool_with_file
        with pytest.raises(Exception, match="Permission denied"):
            tool.forward("../../etc/passwd")

    def test_upload_empty_file_raises(self, mock_minio_client, temp_workspace):
        tool = UploadToS3Tool(
            workspace_path=temp_workspace,
            minio_client=mock_minio_client,
            user_id="user1",
            tenant_id="tenant1",
        )
        empty_file = os.path.join(temp_workspace, "empty.txt")
        with open(empty_file, "w") as f:
            pass  # Create empty file
        with pytest.raises(Exception, match="empty"):
            tool.forward("empty.txt")

    def test_upload_file_too_large_raises(self, mock_minio_client, temp_workspace):
        tool = UploadToS3Tool(
            workspace_path=temp_workspace,
            minio_client=mock_minio_client,
            user_id="user1",
            tenant_id="tenant1",
        )
        large_file = os.path.join(temp_workspace, "large.bin")
        with open(large_file, "wb") as f:
            f.write(b"x")  # Just 1 byte, but we'll mock the size check
        # Override the max size to test
        tool.MAX_UPLOAD_SIZE = 0
        with pytest.raises(Exception, match="too large"):
            tool.forward("large.bin")

    def test_upload_minio_failure_raises(self, tool_with_file, mock_minio_client):
        tool, _ = tool_with_file
        mock_minio_client.upload_file.return_value = (False, "Upload failed")
        with pytest.raises(Exception, match="Failed to upload"):
            tool.forward("test_report.txt")

    def test_upload_does_not_generate_presigned_url(
        self, tool_with_file, mock_minio_client
    ):
        tool, _ = tool_with_file
        mock_minio_client.get_file_url.side_effect = RuntimeError("signing failed")

        result = json.loads(tool.forward("test_report.txt"))

        assert result["status"] == "success"
        assert "presigned_url" not in result
        mock_minio_client.get_file_url.assert_not_called()

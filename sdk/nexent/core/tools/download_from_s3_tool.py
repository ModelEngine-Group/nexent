import json
import logging
import os
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic.fields import FieldInfo
from smolagents.tools import Tool

from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import ToolSign, ToolCategory

logger = logging.getLogger("download_from_s3_tool")


class DownloadFromS3Tool(Tool):
    """Tool for downloading files from S3/MinIO storage to local workspace."""

    name = "download_from_s3"
    description = (
        "Download a file from S3/MinIO storage to the local workspace. "
        "Accepts s3://bucket/key, /bucket/key, or plain object key paths. "
        "The file will be saved to the workspace directory. "
        "Returns the local file path for use with other tools like read_file or analyze_text_file."
    )
    description_zh = (
        "从 S3/MinIO 存储下载文件到当前运行的隔离工作区。"
        "支持 s3://bucket/key、/bucket/key 或对象键格式，并返回可供其他工具使用的本地路径。"
    )

    inputs = {
        "s3_path": {
            "type": "string",
            "description": (
                "S3 path of the file to download. "
                "Supported formats: 's3://bucket/key', '/bucket/key', or plain object key."
            ),
            "description_zh": (
                "要下载的 S3 路径，支持 s3://bucket/key、/bucket/key 或对象键。"
            ),
        },
        "local_filename": {
            "type": "string",
            "description": (
                "Optional local filename to save as. "
                "If not specified, uses the original filename from the S3 path."
            ),
            "description_zh": (
                "可选的工作区相对文件名；未指定时使用 S3 路径中的原始文件名。"
            ),
            "nullable": True,
        },
    }
    output_type = "string"
    category = ToolCategory.FILE.value
    tool_sign = ToolSign.FILE_OPERATION.value

    # Maximum file size for download (100 MB)
    MAX_DOWNLOAD_SIZE = 100 * 1024 * 1024

    def __init__(
        self,
        workspace_path: str = Field(description="Local workspace root path", default="/mnt/nexent"),
        minio_client: object = Field(description="MinIO storage client", default=None, exclude=True),
        user_id: str = Field(description="Current user ID for access control", default="", exclude=True),
        tenant_id: str = Field(description="Current tenant ID for access control", default="", exclude=True),
        observer: MessageObserver = Field(description="Message observer", default=None, exclude=True),
        validate_url_access: object = Field(description="Backend-owned access validator", default=None, exclude=True),
        on_download: object = Field(description="Download synchronization callback", default=None, exclude=True),
    ):
        super().__init__()
        # Guard against FieldInfo objects when called without arguments
        _default_ws = "/mnt/nexent"
        if not isinstance(workspace_path, str):
            workspace_path = _default_ws
        self.workspace_path = os.path.abspath(workspace_path) if workspace_path else _default_ws
        self.minio_client = minio_client if not isinstance(minio_client, FieldInfo) else None
        self.user_id = user_id if isinstance(user_id, str) else ""
        self.tenant_id = tenant_id if isinstance(tenant_id, str) else ""
        self.observer = observer if hasattr(observer, 'add_message') else None
        self.validate_url_access = validate_url_access if callable(validate_url_access) else None
        self.on_download = on_download if callable(on_download) else None

    # ------------------------------------------------------------------
    # Access control helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_s3_path(s3_path: str) -> tuple:
        """Parse an S3 path into (bucket, object_key).

        Supports:
        - s3://bucket/key
        - s3:/bucket/key
        - /bucket/key
        - plain object key (bucket will be None)
        """
        if not s3_path or not isinstance(s3_path, str):
            raise ValueError("S3 path cannot be empty")

        s3_path = s3_path.strip()

        if s3_path.startswith("s3://"):
            stripped = s3_path[5:]
        elif s3_path.startswith("s3:/"):
            stripped = s3_path[4:].lstrip("/")
        elif s3_path.startswith("/"):
            stripped = s3_path.lstrip("/")
        else:
            # Plain object key, no bucket info
            return None, s3_path

        parts = stripped.split("/", 1)
        if len(parts) == 2 and parts[0] and parts[1] and ":" not in parts[0]:
            return parts[0], parts[1]

        raise ValueError(f"Invalid S3 path format: {s3_path}")

    def _check_access(self, object_key: str) -> bool:
        """Check if the current user has access to the given object key.

        Mirrors the access rules in backend/services/file_management_service.py:
        - knowledge_base/*: all authenticated users
        - images_in_attachments/*: all authenticated users
        - attachments/{user_id}/*: only the owner
        - skill-files/{user_id}/*: only the owner
        - workspace/{user_id}/*: only the owner
        - attachments/asset_owner/*: only asset_owner tenant
        """
        if not self.user_id:
            return False

        key = object_key

        if key.startswith("attachments/asset_owner/"):
            # Asset owner files require specific tenant
            return False  # Conservative default; backend will set proper tenant_id

        if key.startswith("knowledge_base/"):
            return True

        if key.startswith("images_in_attachments/"):
            return True

        if key.startswith("skill-files/"):
            return key.startswith(f"skill-files/{self.user_id}/")

        if key.startswith("workspace/"):
            parts = key.split("/")
            return (
                len(parts) >= 5
                and parts[1] == self.user_id
                and parts[3] == "outputs"
            )

        # attachments/{user_id}/...
        if key.startswith("attachments/"):
            if key.startswith(f"attachments/{self.user_id}/"):
                return True
            legacy_name = key.removeprefix("attachments/")
            return bool(legacy_name) and "/" not in legacy_name

        return False

    def _validate_access(self, s3_path: str, object_key: str) -> None:
        """Validate access with the application callback, falling back conservatively."""
        if self.validate_url_access is not None:
            self.validate_url_access([s3_path])
            return
        if not self._check_access(object_key):
            raise PermissionError(
                f"Permission denied: you do not have access to '{s3_path}'."
            )

    def _resolve_local_path(self, object_key: str, local_filename: Optional[str]) -> Path:
        """Resolve a download target without allowing workspace traversal."""
        filename = local_filename or os.path.basename(object_key)
        if not filename:
            raise ValueError(f"Cannot determine filename from S3 path: {object_key}")

        workspace = Path(self.workspace_path).resolve()
        local_path = (workspace / filename).resolve()
        try:
            local_path.relative_to(workspace)
        except ValueError as exc:
            raise PermissionError(
                "Permission denied: resolved path is outside the workspace directory."
            ) from exc
        return local_path

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    def forward(self, s3_path: str, local_filename: str = None) -> str:
        try:
            if self.observer:
                card_content = [{"icon": "download", "text": f"Downloading {s3_path}"}]
                self.observer.add_message("", ProcessType.CARD, json.dumps(card_content, ensure_ascii=False))

            # 1. Validate inputs
            if not s3_path or not s3_path.strip():
                raise Exception("S3 path cannot be empty")

            if self.minio_client is None:
                raise Exception("MinIO client is not configured. Cannot download files from S3.")

            # 2. Parse S3 path
            bucket, object_key = self._parse_s3_path(s3_path)

            # 3. Access control
            authorization_path = s3_path
            if not s3_path.startswith(("s3://", "s3:/", "/")):
                authorization_bucket = bucket or getattr(self.minio_client, "default_bucket", None) or "nexent"
                authorization_path = f"s3://{authorization_bucket}/{object_key}"
            self._validate_access(authorization_path, object_key)

            # 4. Check file size before downloading
            file_size = self.minio_client.get_file_size(object_key, bucket)
            if file_size > self.MAX_DOWNLOAD_SIZE:
                raise Exception(
                    f"File too large: {file_size} bytes (max {self.MAX_DOWNLOAD_SIZE} bytes). "
                    f"Please use a smaller file."
                )
            if file_size == 0:
                raise Exception(f"File not found or empty: {s3_path}")

            # 5. Determine local save path
            filename = local_filename or os.path.basename(object_key)
            local_path = self._resolve_local_path(object_key, local_filename)

            # Create parent directories if needed
            local_path.parent.mkdir(parents=True, exist_ok=True)

            # 6. Download from MinIO
            success, msg = self.minio_client.download_file(object_key, str(local_path), bucket)
            if not success:
                raise Exception(f"Failed to download file from S3: {msg}")

            logger.info(f"Successfully downloaded {s3_path} -> {local_path} ({file_size} bytes)")

            # 7. Return result
            relative_path = os.path.relpath(str(local_path), self.workspace_path)
            result = {
                "status": "success",
                "s3_path": s3_path,
                "local_path": str(local_path),
                "relative_path": relative_path,
                "filename": filename,
                "file_size_bytes": file_size,
                "message": f"File downloaded successfully to {relative_path}",
            }
            if self.on_download is not None:
                self.on_download(dict(result))
            return json.dumps(result, ensure_ascii=False)

        except ValueError as e:
            logger.error(f"Invalid S3 path: {e}")
            raise Exception(f"Invalid S3 path: {e}")
        except Exception as e:
            logger.error(f"Download failed: {e}")
            raise Exception(f"Failed to download file: {e}")

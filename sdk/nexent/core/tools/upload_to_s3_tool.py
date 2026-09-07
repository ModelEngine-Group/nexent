import json
import logging
import mimetypes
import os
from pathlib import Path, PurePosixPath

from pydantic import Field
from pydantic.fields import FieldInfo
from smolagents.tools import Tool

from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import ToolSign, ToolCategory

logger = logging.getLogger("upload_to_s3_tool")


class UploadToS3Tool(Tool):
    """Tool for uploading files from local workspace to S3/MinIO storage."""

    name = "upload_to_s3"
    description = (
        "Upload a file from the local workspace to S3/MinIO storage. "
        "The file path must be within the workspace directory. A relative path such as "
        "'report.pdf' is resolved from the run outputs directory; do not prefix it with "
        "'outputs/' when creating the file because code already runs in that directory. "
        "Returns a permanent S3 URL. Use that S3 URL in user-facing Markdown links "
        "and images; never create or expose a presigned URL in the final answer."
    )
    description_zh = (
        "将当前运行工作区中的文件上传到 S3/MinIO。"
        "相对路径（如 report.pdf）从本次运行的 outputs 目录解析；代码已经在该目录运行，"
        "创建文件时不要再添加 outputs/ 前缀。返回永久 S3 对象地址；最终回答中的文件链接和"
        "图片必须使用该 S3 地址，不要创建或暴露预签名链接。"
    )

    inputs = {
        "file_path": {
            "type": "string",
            "description": (
                "Local file path within the workspace. Use a bare path relative to the "
                "run outputs directory (e.g., 'report.pdf') or an absolute path."
            ),
            "description_zh": (
                "工作区内的本地文件路径，可以使用相对于本次 outputs 目录的裸路径"
                "（如 report.pdf）或绝对路径。"
            ),
        },
        "target_filename": {
            "type": "string",
            "description": (
                "Optional target filename in S3 storage. "
                "If not specified, uses the original local filename."
            ),
            "description_zh": (
                "可选的 S3 目标文件名；未指定时使用原始本地文件名。"
            ),
            "nullable": True,
        },
    }
    output_type = "string"
    category = ToolCategory.FILE.value
    tool_sign = ToolSign.FILE_OPERATION.value

    # Maximum file size for upload (100 MB)
    MAX_UPLOAD_SIZE = 100 * 1024 * 1024

    def __init__(
        self,
        workspace_path: str = Field(description="Local workspace root path", default="/mnt/nexent"),
        minio_client: object = Field(description="MinIO storage client", default=None, exclude=True),
        user_id: str = Field(description="Current user ID for access control", default="", exclude=True),
        tenant_id: str = Field(description="Current tenant ID for access control", default="", exclude=True),
        observer: MessageObserver = Field(description="Message observer", default=None, exclude=True),
        run_id: str = Field(description="Current agent run ID", default="", exclude=True),
        on_upload: object = Field(description="Upload event callback", default=None, exclude=True),
        ensure_local_file: object = Field(description="Sandbox file materializer", default=None, exclude=True),
        uploaded_paths: object = Field(description="Shared uploaded path registry", default=None, exclude=True),
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
        self.run_id = run_id if isinstance(run_id, str) else ""
        self.on_upload = on_upload if callable(on_upload) else None
        self.ensure_local_file = ensure_local_file if callable(ensure_local_file) else None
        self.uploaded_paths: set[str] = uploaded_paths if isinstance(uploaded_paths, set) else set()

    def _validate_path(self, file_path: str) -> str:
        """Validate and resolve file path within the workspace.

        Returns:
            Absolute path within workspace.

        Raises:
            Exception: If path is outside workspace or invalid.
        """
        workspace = Path(self.workspace_path).resolve()
        if os.path.isabs(file_path):
            abs_path = Path(file_path).resolve()
        else:
            abs_path = (workspace / file_path).resolve()

        try:
            abs_path.relative_to(workspace)
        except ValueError as exc:
            raise Exception(
                f"Permission denied: file path must be within the workspace directory "
                f"'{self.workspace_path}'. Attempted path '{abs_path}' is outside the allowed area."
            ) from exc

        return str(abs_path)

    def _build_s3_key(self, filename: str) -> str:
        """Build the S3 object key for the uploaded file.

        Files are stored under: workspace/{user_id}/{run_id}/outputs/{filename}
        """
        target_path = PurePosixPath(str(filename).replace("\\", "/"))
        if target_path.is_absolute() or ".." in target_path.parts:
            raise ValueError("Target filename must stay within the output prefix")
        target_parts = tuple(part for part in target_path.parts if part not in ("", "."))
        if target_parts[:1] == ("outputs",):
            target_parts = target_parts[1:]
        if not target_parts:
            raise ValueError("Target filename cannot be empty")
        safe_name = "/".join(target_parts)
        safe_user = self.user_id.strip()
        safe_run = self.run_id.strip()
        if not safe_user or not safe_run:
            raise ValueError("User and run IDs are required for isolated uploads")
        if any(
            separator in value
            for value in (safe_user, safe_run)
            for separator in ("/", "\\")
        ):
            raise ValueError("User and run IDs must be single path segments")
        return f"workspace/{safe_user}/{safe_run}/outputs/{safe_name}"

    def _upload_path_candidates(self, file_path: str) -> list[str]:
        """Return safe local candidates in generated-output lookup order."""
        if os.path.isabs(file_path):
            return [self._validate_path(file_path)]

        normalized = str(file_path).replace("\\", "/")
        relative_path = PurePosixPath(normalized)
        if relative_path.parts[:1] == ("outputs",):
            # Accept the workspace-root form for compatibility, but never add a
            # second outputs segment.
            return [self._validate_path(normalized)]

        return [
            self._validate_path(str(PurePosixPath("outputs") / relative_path)),
            self._validate_path(normalized),
        ]

    def forward(self, file_path: str, target_filename: str = None) -> str:
        try:
            if self.observer:
                card_content = [{"icon": "upload", "text": f"Uploading {file_path}"}]
                self.observer.add_message("", ProcessType.CARD, json.dumps(card_content, ensure_ascii=False))

            # 1. Validate inputs
            if not file_path or not file_path.strip():
                raise Exception("File path cannot be empty")

            if self.minio_client is None:
                raise Exception("MinIO client is not configured. Cannot upload files to S3.")

            if not self.user_id:
                raise Exception("User authentication required for uploading files to S3.")
            # 2. Validate local path
            candidates = self._upload_path_candidates(file_path)
            abs_path = next((path for path in candidates if os.path.exists(path)), candidates[0])

            if not os.path.exists(abs_path) and self.ensure_local_file is not None:
                self.ensure_local_file(abs_path)
                abs_path = next(
                    (path for path in candidates if os.path.exists(path)),
                    candidates[0],
                )

            # 3. Check file exists and is a regular file
            if not os.path.exists(abs_path):
                raise Exception(f"File does not exist: {file_path}")

            if not os.path.isfile(abs_path):
                raise Exception(f"Path is not a regular file: {file_path}")

            # 4. Check file size
            file_size = os.path.getsize(abs_path)
            if file_size > self.MAX_UPLOAD_SIZE:
                raise Exception(
                    f"File too large: {file_size} bytes (max {self.MAX_UPLOAD_SIZE} bytes). "
                    f"Please use a smaller file."
                )
            if file_size == 0:
                raise Exception(f"File is empty: {file_path}")

            # 5. Determine target filename and S3 key
            target_name = target_filename or os.path.basename(abs_path)
            filename = os.path.basename(target_name)
            s3_key = self._build_s3_key(target_name)

            # 6. Upload to MinIO
            success, result = self.minio_client.upload_file(abs_path, s3_key)
            if not success:
                raise Exception(f"Failed to upload file to S3: {result}")

            # 7. Build the permanent S3 reference. Browser-facing URLs are
            # derived by the frontend and authenticated file API at render time.
            bucket = self.minio_client.default_bucket or "default"
            s3_url = f"s3://{bucket}/{s3_key}"

            logger.info(f"Successfully uploaded {abs_path} -> {s3_url} ({file_size} bytes)")

            # 8. Return result
            relative_path = os.path.relpath(abs_path, self.workspace_path)
            response = {
                "status": "success",
                "local_path": relative_path,
                "s3_url": s3_url,
                "filename": filename,
                "object_name": s3_key,
                "name": filename,
                "type": "file",
                "size": file_size,
                "url": s3_url,
                "mime_type": mimetypes.guess_type(filename)[0] or "application/octet-stream",
                "file_size_bytes": file_size,
                "message": f"File uploaded successfully to {s3_url}",
            }
            self.uploaded_paths.add(os.path.normcase(os.path.abspath(abs_path)))
            if self.on_upload is not None:
                self.on_upload(dict(response))
            return json.dumps(response, ensure_ascii=False)

        except Exception as e:
            logger.error(f"Upload failed: {e}")
            raise Exception(f"Failed to upload file: {e}")

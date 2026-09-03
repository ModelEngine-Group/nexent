"""Shared input normalization for backend and SDK Skill uploads."""

import io


def normalize_skill_upload(file_content: bytes | str | io.BytesIO, file_type: str = "auto", *, filename: str | None = None):
    """Return bytes and format, preserving the optional SDK filename hint."""
    if isinstance(file_content, str):
        content = file_content.encode("utf-8")
    elif isinstance(file_content, io.BytesIO):
        content = file_content.getvalue()
    else:
        content = file_content
    if file_type == "auto":
        file_type = "zip" if content.startswith(b"PK") or (filename and filename.endswith(".zip")) else "md"
    return content, file_type

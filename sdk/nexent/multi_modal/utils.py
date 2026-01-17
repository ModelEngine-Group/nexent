import base64
import logging
from datetime import datetime
import uuid
from typing import Literal, Optional, Tuple
import mimetypes
from pathlib import PurePosixPath


logger = logging.getLogger("multi_modal")

UrlType = Literal["http", "https", "s3"]


def is_url(url: str) -> Optional[UrlType]:
    """
    Classify a string URL as HTTP(S) or S3.

    Args:
        url: URL candidate

    Returns:
        'http', 'https', or 's3' when the input matches the respective
        scheme. Returns None when the input is not a supported URL.
    """
    if not url or not isinstance(url, str):
        return None

    url = url.strip()

    if url.startswith("http://"):
        return "http"

    if url.startswith("https://"):
        return "https"

    if url.startswith("s3://"):
        bucket_path = url.replace("s3://", "", 1)
        bucket_object = bucket_path.split("/", 1)
        if len(bucket_object) == 2 and all(bucket_object):
            return "s3"
        return None

    if url.startswith("/"):
        stripped = url.lstrip("/")
        parts = stripped.split("/", 1)
        if len(parts) == 2 and all(parts):
            return "s3"
        return None

    return None


def bytes_to_base64(bytes_data: bytes, content_type: str = "application/octet-stream") -> str:
    """
    Convert bytes to base64 data URI string

    Args:
        bytes_data: File content as bytes
        content_type: MIME type (e.g., 'image/png', 'video/mp4', 'application/pdf')

    Returns:
        Base64 data URI string (e.g., "data:image/png;base64,...")
    """
    if not bytes_data:
        raise ValueError("bytes_data cannot be empty")

    b64_bytes = base64.b64encode(bytes_data)
    b64_string = b64_bytes.decode("utf-8")
    return f"data:{content_type};base64,{b64_string}"


def guess_content_type_from_url(url: str) -> str:
    """
    Guess content type from URL file extension

    Args:
        url: URL string

    Returns:
        MIME type string
    """
    # Extract file extension
    url_without_params = url.split("?")[0]  # Remove query params
    file_ext = PurePosixPath(url_without_params).suffix.lower()

    # Try mimetypes first
    content_type, _ = mimetypes.guess_type(url_without_params)
    if content_type:
        return content_type

    # Fallback to common types
    common_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".mp4": "video/mp4",
        ".avi": "video/x-msvideo",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".pdf": "application/pdf",
        ".txt": "text/plain",
        ".json": "application/json",
    }

    return common_types.get(file_ext, "application/octet-stream")


def base64_to_bytes(base64_data: str) -> Tuple[bytes, str]:
    """
    Convert base64 data URI to bytes and extract content type

    Args:
        base64_data: Base64 data URI string (e.g., "data:image/png;base64,...")

    Returns:
        Tuple[bytes, content_type]: File content as bytes and MIME type

    Raises:
        ValueError: If base64_data format is invalid
    """
    if not base64_data or not isinstance(base64_data, str):
        raise ValueError("base64_data must be a non-empty string")

    # Check if it is a data URI
    if base64_data.startswith("data:"):
        # Parse data URI: data:content/type;base64,<data>
        parts = base64_data.split(",", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid data URI format: {base64_data[:50]}...")

        header = parts[0]
        data = parts[1]

        # Extract content type
        if ";base64" in header:
            content_type = header.replace("data:", "").replace(";base64", "")
        else:
            content_type = header.replace("data:", "")

        if not content_type:
            content_type = "application/octet-stream"

        # Decode base64
        try:
            bytes_data = base64.b64decode(data)
            return bytes_data, content_type
        except Exception as e:
            raise ValueError(f"Failed to decode base64 data: {e}")
    else:
        # Assume it is raw base64 string without data URI prefix
        try:
            bytes_data = base64.b64decode(base64_data)
            return bytes_data, "application/octet-stream"
        except Exception as e:
            raise ValueError(f"Failed to decode base64 string: {e}")


def generate_object_name(file_extension: str = "") -> str:
    """
    Generate unique object name for MinIO upload

    Args:
        file_extension: File extension (e.g., '.png', '.jpg')

    Returns:
        Unique object name string
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = str(uuid.uuid4())[:8]

    if file_extension and not file_extension.startswith("."):
        file_extension = "." + file_extension

    return f"{timestamp}_{unique_id}{file_extension}"


def detect_content_type_from_bytes(bytes_data: bytes) -> str:
    """
    Detect content type from binary data using magic bytes (file signatures)

    Args:
        bytes_data: Binary data to analyze

    Returns:
        MIME type string (e.g., 'image/png', 'video/mp4')
    """
    if not bytes_data or len(bytes_data) < 4:
        return "application/octet-stream"

    # Get first bytes for magic number detection
    header = bytes_data[:12]

    # PNG: 89 50 4E 47 0D 0A 1A 0A
    if len(bytes_data) >= 8 and header[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"

    # JPEG: FF D8 FF
    if len(bytes_data) >= 3 and header[:3] == b"\xff\xd8\xff":
        return "image/jpeg"

    # GIF: 47 49 46 38 (GIF8)
    if len(bytes_data) >= 6 and header[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"

    # WebP: 52 49 46 46 ... 57 45 42 50 (RIFF....WEBP)
    if len(bytes_data) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"

    # BMP: 42 4D (BM)
    if len(bytes_data) >= 2 and header[:2] == b"BM":
        return "image/bmp"

    # PDF: 25 50 44 46 (%PDF)
    if len(bytes_data) >= 4 and header[:4] == b"%PDF":
        return "application/pdf"

    # Excel (XLSX): 50 4B 03 04 (PK..) - ZIP file format
    if len(bytes_data) >= 4 and header[:4] == b"PK\x03\x04":
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    # MP4: 00 00 00 ?? 66 74 79 70 (ftyp)
    if len(bytes_data) >= 8:
        # Check for ftyp at offset 4
        if header[4:8] == b"ftyp":
            return "video/mp4"
        # Also check for quicktime/mov format
        if header[4:8] == b"qt  ":
            return "video/quicktime"

    # MP3: Check for ID3 tag or MPEG frame sync
    if len(bytes_data) >= 3:
        # ID3 tag: 49 44 33 (ID3)
        if header[:3] == b"ID3":
            return "audio/mpeg"
        # MPEG frame sync: FF FB or FF F3
        if header[:2] == b"\xff\xfb" or header[:2] == b"\xff\xf3":
            return "audio/mpeg"

    # WAV: 52 49 46 46 ... 57 41 56 45 (RIFF....WAVE)
    if len(bytes_data) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WAVE":
        return "audio/wav"

    # OGG: 4F 67 67 53 (OggS)
    if len(bytes_data) >= 4 and header[:4] == b"OggS":
        return "audio/ogg"

    # FLAC: 66 4C 61 43 (fLaC)
    if len(bytes_data) >= 4 and header[:4] == b"fLaC":
        return "audio/flac"

    # WebM: 1A 45 DF A3 (EBML header)
    if len(bytes_data) >= 4 and header[:4] == b"\x1a\x45\xdf\xa3":
        return "video/webm"

    # AVI: 52 49 46 46 ... 41 56 49 20 (RIFF....AVI )
    if len(bytes_data) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"AVI ":
        return "video/x-msvideo"

    # JSON: Check if it starts with { or [
    try:
        if bytes_data[:1] in (b"{", b"["):
            # Try to decode as UTF-8 and parse as JSON
            text = bytes_data[:100].decode("utf-8", errors="ignore").strip()
            if text.startswith(("{", "[")):
                return "application/json"
    except Exception:
        pass

    # Text: Check if it is valid UTF-8 text
    try:
        text = bytes_data[:100].decode("utf-8", errors="strict")
        # If it is mostly printable ASCII, consider it text
        if all(32 <= ord(c) <= 126 or c in "\n\r\t" for c in text[:50]):
            return "text/plain"
    except Exception:
        pass

    # Default: unknown binary
    return "application/octet-stream"


def guess_extension_from_content_type(content_type: str) -> str:
    """
    Guess file extension from content type

    Args:
        content_type: MIME type (e.g., 'image/png', 'video/mp4')

    Returns:
        File extension (e.g., '.png', '.mp4')
    """
    content_type_to_ext = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
        "video/mp4": ".mp4",
        "video/x-msvideo": ".avi",
        "video/quicktime": ".mov",
        "video/webm": ".webm",
        "audio/mpeg": ".mp3",
        "audio/wav": ".wav",
        "audio/ogg": ".ogg",
        "audio/flac": ".flac",
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "text/plain": ".txt",
        "application/json": ".json",
    }

    return content_type_to_ext.get(content_type, "")


def parse_s3_url(s3_url: str) -> Tuple[str, str]:
    """
    Parse S3 URL to extract bucket and object_name

    Supports formats:
    - s3://bucket/key
    - /bucket/key (MinIO path format)

    Args:
        s3_url: S3 URL string

    Returns:
        Tuple[bucket, object_name]

    Raises:
        ValueError: If URL format is not recognized
    """
    if not s3_url:
        raise ValueError("S3 URL cannot be empty")

    if s3_url.startswith('s3://'):
        parts = s3_url.replace('s3://', '').split('/', 1)
        if len(parts) == 2:
            bucket, object_name = parts
            if not bucket or not object_name:
                raise ValueError(f"Invalid s3:// URL format: {s3_url}")
            return bucket, object_name
        raise ValueError(f"Invalid s3:// URL format: {s3_url}")

    if s3_url.startswith('/'):
        parts = s3_url.lstrip('/').split('/', 1)
        if len(parts) == 2:
            bucket, object_name = parts
            return bucket, object_name
        raise ValueError(f"Invalid path format: {s3_url}")

    raise ValueError(f"Unrecognized S3 URL format: {s3_url[:50]}...")
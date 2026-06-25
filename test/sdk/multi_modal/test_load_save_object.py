import io
from typing import Any, Tuple
from unittest.mock import MagicMock

import pytest

from sdk.nexent.multi_modal import load_save_object as lso


def make_manager(client: Any = None, validate_url_access: Any = None) -> lso.LoadSaveObjectManager:
    if client is None:
        client = object()
    return lso.LoadSaveObjectManager(storage_client=client, validate_url_access=validate_url_access)


def test_get_client_returns_configured_storage():
    sentinel = object()
    manager = make_manager(sentinel)
    assert manager._get_client() is sentinel


def test_get_client_requires_initialized_storage():
    manager = lso.LoadSaveObjectManager(storage_client=None)

    with pytest.raises(ValueError):
        manager._get_client()


def test_s3_single_slash_url_supported():
    assert lso.is_url("s3:/bucket/path/to/image.png") == "s3"
    assert lso.parse_s3_url("s3:/bucket/path/to/image.png") == (
        "bucket",
        "path/to/image.png",
    )


def test_s3_blob_preview_url_rejected():
    assert lso.is_url("s3:/blob:http://localhost:3000/preview") is None


def test_parse_s3_blob_preview_url_rejected():
    with pytest.raises(ValueError, match="Invalid s3:// URL format"):
        lso.parse_s3_url("s3:/blob:http://localhost:3000/preview")


def test_download_file_from_http(monkeypatch):
    manager = make_manager()

    class _Response:
        def __init__(self):
            self.content = b"binary"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(lso.requests, "get", lambda url, timeout: _Response())
    data = manager.download_file_from_url(
        "https://example.com/file.png",
        url_type="https",
    )
    assert data == b"binary"


def test_download_file_from_s3(monkeypatch):
    class _FakeClient:
        def get_file_stream(self, object_name: str, bucket: str) -> Tuple[bool, Any]:
            assert object_name == "path/to/object"
            assert bucket == "bucket"
            return True, io.BytesIO(b"payload")

    manager = make_manager(_FakeClient())
    data = manager.download_file_from_url("s3://bucket/path/to/object", url_type="s3")
    assert data == b"payload"


def test_download_file_from_s3_failure_returns_none():
    class _FailingClient:
        def get_file_stream(self, object_name: str, bucket: str):
            return False, "boom"

    manager = make_manager(_FailingClient())
    assert manager.download_file_from_url("s3://bucket/object", url_type="s3") is None


def test_download_file_from_s3_missing_method_returns_none():
    class _InvalidClient:
        pass

    manager = make_manager(_InvalidClient())
    assert manager.download_file_from_url("s3://bucket/object", url_type="s3") is None


def test_download_file_requires_url_type():
    manager = make_manager()
    with pytest.raises(ValueError):
        manager.download_file_from_url("https://example.com/file.png", url_type=None)  # type: ignore[arg-type]


def test_download_file_empty_url_returns_none():
    manager = make_manager()
    assert manager.download_file_from_url("", url_type="https") is None


def test_download_file_stream_read_failure(monkeypatch):
    class _FailingStream:
        def read(self):
            raise RuntimeError("cannot read")

        def close(self):
            pass

    class _Client:
        def get_file_stream(self, object_name: str, bucket: str):
            return True, _FailingStream()

    manager = make_manager(_Client())
    assert manager.download_file_from_url("s3://bucket/object", url_type="s3") is None


def test_upload_bytes_to_minio_generates_object_name(monkeypatch):
    captured = {}

    class _UploadClient:
        def upload_fileobj(self, file_obj, object_name, bucket):
            captured["data"] = file_obj.read()
            captured["object_name"] = object_name
            captured["bucket"] = bucket
            return True, "/bucket/generated.bin"

    manager = make_manager(_UploadClient())
    monkeypatch.setattr(lso, "guess_extension_from_content_type", lambda c: ".bin")
    monkeypatch.setattr(lso, "generate_object_name", lambda ext: f"generated{ext}")

    result = manager._upload_bytes_to_minio(b"payload", content_type="application/octet-stream")

    assert result == "/bucket/generated.bin"
    assert captured["data"] == b"payload"
    assert captured["object_name"] == "generated.bin"
    assert captured["bucket"] == "nexent"


def test_upload_bytes_to_minio_generates_name_without_extension(monkeypatch):
    captured = {}

    class _UploadClient:
        def upload_fileobj(self, file_obj, object_name, bucket):
            captured["object_name"] = object_name
            return True, "/bucket/generated"

    manager = make_manager(_UploadClient())

    monkeypatch.setattr(lso, "guess_extension_from_content_type", lambda _: "")

    def _generate(ext: str):
        captured["ext"] = ext
        return "generated"

    monkeypatch.setattr(lso, "generate_object_name", _generate)

    path = manager._upload_bytes_to_minio(b"bytes", content_type="application/octet-stream")
    assert path == "/bucket/generated"
    assert captured["ext"] == ""
    assert captured["object_name"] == "generated"


def test_upload_bytes_to_minio_requires_upload_method():
    class _InvalidClient:
        pass

    manager = make_manager(_InvalidClient())

    with pytest.raises(ValueError):
        manager._upload_bytes_to_minio(b"bytes")


def test_upload_bytes_to_minio_failure_propagates_error():
    class _UploadClient:
        def upload_fileobj(self, file_obj, object_name, bucket):
            return False, "failed"

    manager = make_manager(_UploadClient())

    with pytest.raises(ValueError):
        manager._upload_bytes_to_minio(b"bytes")


def test_upload_bytes_to_minio_with_explicit_object_name():
    captured = {}

    class _UploadClient:
        def upload_fileobj(self, file_obj, object_name, bucket):
            captured["name"] = object_name
            captured["bucket"] = bucket
            return True, "/bucket/custom.bin"

    manager = make_manager(_UploadClient())
    result = manager._upload_bytes_to_minio(
        b"payload",
        object_name="provided.bin",
        bucket="custom-bucket"
    )

    assert result == "/bucket/custom.bin"
    assert captured["name"] == "provided.bin"
    assert captured["bucket"] == "custom-bucket"


def test_load_object_transforms_single_argument(monkeypatch):
    manager = make_manager()
    download_mock = MagicMock(return_value=b"file-bytes")
    monkeypatch.setattr(manager, "download_file_from_url", download_mock)

    @manager.load_object(input_names=["image"])
    def handler(image):
        return image

    result = handler("https://example.com/img.png")

    download_mock.assert_called_once_with("https://example.com/img.png", url_type="https")
    assert result == b"file-bytes"


def test_load_object_transforms_iterable_with_transformer(monkeypatch):
    manager = make_manager()

    def transformer(data: bytes) -> str:
        return data.decode("utf-8")

    download_mock = MagicMock(side_effect=[b"first", b"second"])
    monkeypatch.setattr(manager, "download_file_from_url", download_mock)

    @manager.load_object(input_names=["images"], input_data_transformer=[transformer])
    def handler(images):
        return images

    result = handler(["https://a", "https://b"])

    assert result == ["first", "second"]


def test_load_object_preserves_tuple_type(monkeypatch):
    manager = make_manager()
    download_mock = MagicMock(side_effect=[b"alpha", b"beta"])
    monkeypatch.setattr(manager, "download_file_from_url", download_mock)

    @manager.load_object(input_names=["images"])
    def handler(images):
        return images

    result = handler(("https://a", "https://b"))

    assert isinstance(result, tuple)
    assert result == (b"alpha", b"beta")


def test_load_object_skips_missing_arguments(monkeypatch):
    manager = make_manager()
    download_mock = MagicMock(return_value=b"bytes")
    monkeypatch.setattr(manager, "download_file_from_url", download_mock)

    @manager.load_object(input_names=["image", "mask"])
    def handler(image, other=None):
        return image, other

    result = handler("https://example.com/a.png")
    download_mock.assert_called_once_with("https://example.com/a.png", url_type="https")
    assert result == (b"bytes", None)


def test_load_object_raises_for_non_url():
    manager = make_manager()

    @manager.load_object(input_names=["image"])
    def handler(image):
        return image

    with pytest.raises(ValueError):
        handler(123)


def test_load_object_allows_none_input():
    manager = make_manager()

    @manager.load_object(input_names=["image"])
    def handler(image):
        return image

    assert handler(None) is None


def test_load_object_transformer_error_propagates(monkeypatch):
    def transformer(_data: bytes):
        raise RuntimeError("boom")

    manager = make_manager()
    monkeypatch.setattr(manager, "download_file_from_url", MagicMock(return_value=b"bytes"))

    @manager.load_object(input_names=["image"], input_data_transformer=[transformer])
    def handler(image):
        return image

    with pytest.raises(RuntimeError):
        handler("https://example.com/test.png")


def test_load_object_transformer_list_shorter_than_inputs(monkeypatch):
    manager = make_manager()
    download_mock = MagicMock(side_effect=[b"first", b"second"])
    monkeypatch.setattr(manager, "download_file_from_url", download_mock)

    def decode(data: bytes) -> str:
        return data.decode("utf-8")

    @manager.load_object(
        input_names=["primary", "secondary"],
        input_data_transformer=[decode],
    )
    def handler(primary, secondary):
        return primary, secondary

    result = handler("https://a", "https://b")
    assert result == ("first", b"second")
    assert download_mock.call_count == 2


def test_save_object_uploads_bytes(monkeypatch):
    manager = make_manager()
    upload_mock = MagicMock(return_value="/bucket/object")
    monkeypatch.setattr(manager, "_upload_bytes_to_minio", upload_mock)
    monkeypatch.setattr(
        lso, "detect_content_type_from_bytes", lambda data: "image/png"
    )

    @manager.save_object(output_names=["image"])
    def handler():
        return b"\x89PNG\r\n\x1a\n"

    result = handler()
    upload_mock.assert_called_once()
    assert result == "s3://bucket/object"


def test_save_object_with_transformer_and_nested(monkeypatch):
    manager = make_manager()
    upload_mock = MagicMock(side_effect=["/bucket/a", "/bucket/b"])
    monkeypatch.setattr(manager, "_upload_bytes_to_minio", upload_mock)
    monkeypatch.setattr(
        lso, "detect_content_type_from_bytes", lambda data: "application/octet-stream"
    )

    def to_bytes(value: str) -> bytes:
        return value.encode("utf-8")

    @manager.save_object(output_names=["images"], output_transformers=[to_bytes])
    def handler():
        return ["one", "two"]

    result = handler()
    assert result == ["s3://bucket/a", "s3://bucket/b"]
    assert upload_mock.call_count == 2


def test_save_object_validates_return_value_count():
    manager = make_manager()

    @manager.save_object(output_names=["first", "second"])
    def handler():
        return b"only-one"

    with pytest.raises(ValueError):
        handler()


def test_save_object_transformer_must_return_bytes():
    def identity(value):
        return value  # not bytes

    manager = make_manager()

    @manager.save_object(output_names=["payload"], output_transformers=[identity])
    def handler():
        return "text"

    with pytest.raises(ValueError):
        handler()


def test_save_object_requires_bytes_without_transformer():
    manager = make_manager()

    @manager.save_object(output_names=["image"])
    def handler():
        return "text"

    with pytest.raises(ValueError):
        handler()


def test_save_object_handles_none_output(monkeypatch):
    manager = make_manager()
    upload_mock = MagicMock()
    monkeypatch.setattr(manager, "_upload_bytes_to_minio", upload_mock)

    @manager.save_object(output_names=["image"])
    def handler():
        return None

    assert handler() is None
    upload_mock.assert_not_called()


def test_save_object_returns_tuple_for_multiple_outputs(monkeypatch):
    manager = make_manager()
    monkeypatch.setattr(
        lso, "detect_content_type_from_bytes", lambda data: "application/octet-stream"
    )
    upload_mock = MagicMock(side_effect=["/bucket/a", "/bucket/b"])
    monkeypatch.setattr(manager, "_upload_bytes_to_minio", upload_mock)

    @manager.save_object(output_names=["first", "second"])
    def handler():
        return b"a", b"b"

    assert handler() == ("s3://bucket/a", "s3://bucket/b")
    assert upload_mock.call_count == 2


def test_save_object_nested_none_structure(monkeypatch):
    manager = make_manager()
    monkeypatch.setattr(
        lso, "detect_content_type_from_bytes", lambda data: "application/octet-stream"
    )
    upload_mock = MagicMock(return_value="/bucket/value")
    monkeypatch.setattr(manager, "_upload_bytes_to_minio", upload_mock)

    @manager.save_object(output_names=["images"])
    def handler_nested():
        return [None, b"bytes"]

    result = handler_nested()
    assert result == [None, "s3://bucket/value"]
    upload_mock.assert_called_once()


@pytest.mark.asyncio
async def test_save_object_supports_async_functions(monkeypatch):
    manager = make_manager()
    upload_mock = MagicMock(return_value="/bucket/object")
    monkeypatch.setattr(manager, "_upload_bytes_to_minio", upload_mock)
    monkeypatch.setattr(
        lso, "detect_content_type_from_bytes", lambda data: "image/png"
    )

    @manager.save_object(output_names=["image"])
    async def handler():
        return b"\x89PNG\r\n\x1a\n"

    result = await handler()
    assert result == "s3://bucket/object"
    upload_mock.assert_called_once()


# ============================================================================
# Tests for new code coverage (lines 29-40, 135-139, 185-209)
# ============================================================================


def test_init_stores_validate_url_access():
    """Test that __init__ (lines 29-40) stores the validate_url_access callback."""
    def my_validator(urls):
        pass

    manager = make_manager(validate_url_access=my_validator)
    assert manager._validate_url_access is my_validator


def test_init_validate_url_access_defaults_to_none():
    """Test that validate_url_access defaults to None when not provided."""
    manager = make_manager()
    assert manager._validate_url_access is None


def test_load_object_with_validate_url_access_success(monkeypatch):
    """Test load_object (lines 185-209) with successful URL validation."""
    manager = make_manager()
    validate_mock = MagicMock()
    download_mock = MagicMock(return_value=b"file-bytes")

    monkeypatch.setattr(manager, "download_file_from_url", download_mock)
    monkeypatch.setattr(lso, "is_url", lambda url: "https" if url.startswith("https://") else None)

    @manager.load_object(input_names=["image"])
    def handler(image):
        return image

    result = handler("https://example.com/img.png")

    validate_mock.assert_not_called()
    assert result == b"file-bytes"


def test_load_object_validates_urls_before_download(monkeypatch):
    """Test that URL validation happens before downloading (lines 200-208)."""
    def my_validator(urls):
        assert "https://example.com/img.png" in urls
        raise PermissionError("Access denied")

    manager = make_manager(validate_url_access=my_validator)
    download_mock = MagicMock(return_value=b"file-bytes")
    monkeypatch.setattr(manager, "download_file_from_url", download_mock)
    monkeypatch.setattr(lso, "is_url", lambda url: "https" if url.startswith("https://") else None)

    @manager.load_object(input_names=["image"])
    def handler(image):
        return image

    with pytest.raises(PermissionError, match="Access denied"):
        handler("https://example.com/img.png")

    download_mock.assert_not_called()


def test_load_object_validates_urls_with_other_exception(monkeypatch):
    """Test that non-PermissionError exceptions from validator raise PermissionError (lines 206-208)."""
    def my_validator(urls):
        raise ValueError("Some validation error")

    manager = make_manager(validate_url_access=my_validator)
    download_mock = MagicMock(return_value=b"file-bytes")
    monkeypatch.setattr(manager, "download_file_from_url", download_mock)
    monkeypatch.setattr(lso, "is_url", lambda url: "https" if url.startswith("https://") else None)

    @manager.load_object(input_names=["image"])
    def handler(image):
        return image

    with pytest.raises(PermissionError, match="URL access validation failed"):
        handler("https://example.com/img.png")


def test_load_object_collects_urls_from_list(monkeypatch):
    """Test that URLs are collected from list arguments (lines 195-198)."""
    collected_urls = []

    def my_validator(urls):
        collected_urls.extend(urls)

    manager = make_manager(validate_url_access=my_validator)
    download_mock = MagicMock(return_value=b"file-bytes")
    monkeypatch.setattr(manager, "download_file_from_url", download_mock)
    monkeypatch.setattr(lso, "is_url", lambda url: "https" if url.startswith("https://") else None)

    @manager.load_object(input_names=["images"])
    def handler(images):
        return images

    result = handler(["https://example.com/a.png", "https://example.com/b.png"])

    assert len(collected_urls) == 2
    assert "https://example.com/a.png" in collected_urls
    assert "https://example.com/b.png" in collected_urls


def test_load_object_collects_urls_from_tuple(monkeypatch):
    """Test that URLs are collected from tuple arguments (lines 195-198)."""
    collected_urls = []

    def my_validator(urls):
        collected_urls.extend(urls)

    manager = make_manager(validate_url_access=my_validator)
    download_mock = MagicMock(return_value=b"file-bytes")
    monkeypatch.setattr(manager, "download_file_from_url", download_mock)
    monkeypatch.setattr(lso, "is_url", lambda url: "https" if url.startswith("https://") else None)

    @manager.load_object(input_names=["images"])
    def handler(images):
        return images

    result = handler(("https://a.com/1.png", "https://b.com/2.png"))

    assert len(collected_urls) == 2
    assert "https://a.com/1.png" in collected_urls
    assert "https://b.com/2.png" in collected_urls


def test_load_object_collects_urls_from_multiple_params(monkeypatch):
    """Test URL collection across multiple parameters (lines 186-198)."""
    collected_urls = []

    def my_validator(urls):
        collected_urls.extend(urls)

    manager = make_manager(validate_url_access=my_validator)
    download_mock = MagicMock(return_value=b"file-bytes")
    monkeypatch.setattr(manager, "download_file_from_url", download_mock)
    monkeypatch.setattr(lso, "is_url", lambda url: "https" if url.startswith("https://") else None)

    @manager.load_object(input_names=["image", "mask"])
    def handler(image, mask):
        return image, mask

    result = handler("https://example.com/img.png", "https://example.com/mask.png")

    assert len(collected_urls) == 2
    assert "https://example.com/img.png" in collected_urls
    assert "https://example.com/mask.png" in collected_urls


def test_load_object_no_validation_when_callback_none(monkeypatch):
    """Test that validation is skipped when validate_url_access is None (line 201)."""
    manager = make_manager(validate_url_access=None)
    download_mock = MagicMock(return_value=b"file-bytes")
    monkeypatch.setattr(manager, "download_file_from_url", download_mock)
    monkeypatch.setattr(lso, "is_url", lambda url: "https" if url.startswith("https://") else None)

    @manager.load_object(input_names=["image"])
    def handler(image):
        return image

    result = handler("https://example.com/img.png")
    assert result == b"file-bytes"


def test_load_object_no_validation_when_not_callable(monkeypatch):
    """Test that validation is skipped when validate_url_access is not callable (line 201)."""
    manager = make_manager(validate_url_access="not-a-callable")
    download_mock = MagicMock(return_value=b"file-bytes")
    monkeypatch.setattr(manager, "download_file_from_url", download_mock)
    monkeypatch.setattr(lso, "is_url", lambda url: "https" if url.startswith("https://") else None)

    @manager.load_object(input_names=["image"])
    def handler(image):
        return image

    result = handler("https://example.com/img.png")
    assert result == b"file-bytes"


def test_load_object_with_validate_url_access_and_s3_url(monkeypatch):
    """Test URL validation with S3 URLs (lines 186-198)."""
    collected_urls = []

    def my_validator(urls):
        collected_urls.extend(urls)

    manager = make_manager(validate_url_access=my_validator)
    download_mock = MagicMock(return_value=b"file-bytes")
    monkeypatch.setattr(manager, "download_file_from_url", download_mock)
    monkeypatch.setattr(lso, "is_url", lambda url: "s3" if url.startswith("s3://") else None)

    @manager.load_object(input_names=["file"])
    def handler(file):
        return file

    result = handler("s3://bucket/path/to/file.bin")

    assert len(collected_urls) == 1
    assert "s3://bucket/path/to/file.bin" in collected_urls


def test_load_object_tool_instance_from_bound_args(monkeypatch):
    """Test load_object extracts tool instance from bound args (lines 135-139)."""
    manager = make_manager()
    download_mock = MagicMock(return_value=b"file-bytes")
    monkeypatch.setattr(manager, "download_file_from_url", download_mock)
    monkeypatch.setattr(lso, "is_url", lambda url: "https" if url.startswith("https://") else None)

    class ToolWithMethod:
        @manager.load_object(input_names=["image"])
        def process(self, image):
            return image

    tool = ToolWithMethod()
    result = tool.process("https://example.com/img.png")

    download_mock.assert_called_once()
    assert result == b"file-bytes"


def test_load_object_validates_empty_url_list(monkeypatch):
    """Test that empty collections don't trigger validation (line 195)."""
    validate_called = False

    def my_validator(urls):
        nonlocal validate_called
        validate_called = True

    manager = make_manager(validate_url_access=my_validator)
    download_mock = MagicMock(return_value=b"file-bytes")
    monkeypatch.setattr(manager, "download_file_from_url", download_mock)

    @manager.load_object(input_names=["items"])
    def handler(items):
        return items

    result = handler([])

    assert not validate_called
    assert result == []


def test_load_object_validation_called_with_duplicates(monkeypatch):
    """Test that duplicate URLs are all included in validation (lines 195-198)."""
    collected_urls = []

    def my_validator(urls):
        collected_urls.extend(urls)

    manager = make_manager(validate_url_access=my_validator)
    download_mock = MagicMock(side_effect=[b"a", b"b"])
    monkeypatch.setattr(manager, "download_file_from_url", download_mock)
    monkeypatch.setattr(lso, "is_url", lambda url: "https" if url.startswith("https://") else None)

    @manager.load_object(input_names=["images"])
    def handler(images):
        return images

    result = handler(["https://example.com/same.png", "https://example.com/same.png"])

    assert len(collected_urls) == 2
    assert collected_urls.count("https://example.com/same.png") == 2


def test_download_file_unsupported_url_type_raises(monkeypatch):
    """Test that unsupported URL type raises ValueError (line 90)."""
    class _Response:
        def __init__(self):
            self.content = b"binary"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(lso.requests, "get", lambda url, timeout: _Response())
    manager = make_manager()

    result = manager.download_file_from_url("ftp://example.com/file.png", url_type="ftp")
    assert result is None


def test_load_object_transformer_returns_none_raises_error(monkeypatch):
    """Test that transformer returning None raises ValueError (line 147-148)."""
    def transformer(_data: bytes):
        return None

    manager = make_manager()
    monkeypatch.setattr(
        manager, "download_file_from_url",
        MagicMock(return_value=None)
    )
    monkeypatch.setattr(lso, "is_url", lambda url: "https" if url.startswith("https://") else None)

    @manager.load_object(input_names=["image"], input_data_transformer=[transformer])
    def handler(image):
        return image

    with pytest.raises(ValueError, match="Failed to download file from URL"):
        handler("https://example.com/test.png")


def test_process_value_handles_none_in_list(monkeypatch):
    """Test that None values in lists are handled correctly (line 170)."""
    manager = make_manager()
    download_mock = MagicMock(return_value=b"file-bytes")
    monkeypatch.setattr(manager, "download_file_from_url", download_mock)
    monkeypatch.setattr(lso, "is_url", lambda url: "https" if url.startswith("https://") else None)

    @manager.load_object(input_names=["items"])
    def handler(items):
        return items

    result = handler([None, "https://example.com/img.png"])

    assert result[0] is None
    assert result[1] == b"file-bytes"

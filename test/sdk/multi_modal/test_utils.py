import base64

import pytest

from sdk.nexent.multi_modal import utils


def test_is_url_variants():
    assert utils.is_url("https://example.com/image.png") == "https"
    assert utils.is_url("http://example.com/image.png") == "http"
    assert utils.is_url("s3://bucket/key") == "s3"
    assert utils.is_url("/bucket/key") == "s3"
    assert utils.is_url("not-a-url") is None
    assert utils.is_url(123) is None  # type: ignore[arg-type]


def test_is_url_requires_bucket_and_key():
    assert utils.is_url("/bucket") is None
    assert utils.is_url("s3://bucket/") is None
    assert utils.is_url("") is None


def test_bytes_to_base64_and_back():
    data = b"sample"
    encoded = utils.bytes_to_base64(data, content_type="text/plain")
    assert encoded.startswith("data:text/plain;base64,")
    decoded, content_type = utils.base64_to_bytes(encoded)
    assert decoded == data
    assert content_type == "text/plain"


def test_bytes_to_base64_requires_data():
    with pytest.raises(ValueError):
        utils.bytes_to_base64(b"")


def test_base64_to_bytes_without_prefix():
    payload = base64.b64encode(b"raw-data").decode("utf-8")
    decoded, content_type = utils.base64_to_bytes(payload)
    assert decoded == b"raw-data"
    assert content_type == "application/octet-stream"


def test_base64_to_bytes_invalid_input():
    with pytest.raises(ValueError):
        utils.base64_to_bytes("data:image/png;base64,invalid!!")


def test_base64_to_bytes_requires_string():
    with pytest.raises(ValueError):
        utils.base64_to_bytes(b"not-a-string")  # type: ignore[arg-type]


def test_base64_to_bytes_invalid_header_format():
    with pytest.raises(ValueError):
        utils.base64_to_bytes("data:image/png;base64")  # missing comma


def test_generate_object_name_appends_extension(monkeypatch: pytest.MonkeyPatch):
    class _FixedDateTime:
        @staticmethod
        def now():
            class _Value:
                def strftime(self, fmt: str) -> str:
                    return "20240102_030405"

            return _Value()

    class _FixedUUID:
        @staticmethod
        def uuid4():
            return "12345678-abcdef"

    monkeypatch.setattr(utils, "datetime", _FixedDateTime())
    monkeypatch.setattr(utils, "uuid", _FixedUUID())

    name = utils.generate_object_name("png")
    assert name == "20240102_030405_12345678.png"


def test_generate_object_name_accepts_dot_prefix(monkeypatch: pytest.MonkeyPatch):
    class _FixedDateTime:
        @staticmethod
        def now():
            class _Value:
                def strftime(self, fmt: str) -> str:
                    return "20240102_030405"

            return _Value()

    class _FixedUUID:
        @staticmethod
        def uuid4():
            return "12345678-abcdef"

    monkeypatch.setattr(utils, "datetime", _FixedDateTime())
    monkeypatch.setattr(utils, "uuid", _FixedUUID())

    name = utils.generate_object_name(".gif")
    assert name.endswith(".gif")


def test_detect_content_type_known_signatures():
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10
    assert utils.detect_content_type_from_bytes(png_bytes) == "image/png"

    pdf_bytes = b"%PDF" + b"\x00" * 10
    assert utils.detect_content_type_from_bytes(pdf_bytes) == "application/pdf"

    jpeg_bytes = b"\xff\xd8\xff" + b"\x00" * 5
    assert utils.detect_content_type_from_bytes(jpeg_bytes) == "image/jpeg"

    gif_bytes = b"GIF89a" + b"\x00" * 6
    assert utils.detect_content_type_from_bytes(gif_bytes) == "image/gif"

    webp_bytes = b"RIFF" + b"\x00" * 4 + b"WEBP"
    assert utils.detect_content_type_from_bytes(webp_bytes) == "image/webp"

    wav_bytes = b"RIFF" + b"\x00" * 4 + b"WAVE"
    assert utils.detect_content_type_from_bytes(wav_bytes) == "audio/wav"


def test_detect_content_type_audio_video_variants():
    mp4_bytes = b"\x00\x00\x00\x20ftyp" + b"\x00" * 10
    assert utils.detect_content_type_from_bytes(mp4_bytes) == "video/mp4"

    mp3_bytes = b"ID3" + b"\x00" * 5
    assert utils.detect_content_type_from_bytes(mp3_bytes) == "audio/mpeg"


def test_detect_content_type_text_and_default():
    text_bytes = b"Hello world"
    assert utils.detect_content_type_from_bytes(text_bytes) == "text/plain"
    assert utils.detect_content_type_from_bytes(b"\x00\x01\x02") == "application/octet-stream"
    json_bytes = b'{"key": "value"}'
    assert utils.detect_content_type_from_bytes(json_bytes) == "application/json"


def test_guess_content_type_from_url():
    assert utils.guess_content_type_from_url("http://example.com/file.webp") == "image/webp"
    assert utils.guess_content_type_from_url("http://example.com/file.unknown") == "application/octet-stream"
    assert utils.guess_content_type_from_url("http://example.com/file.jpg?token=1") == "image/jpeg"


def test_guess_content_type_from_url_uses_case_insensitive_suffix():
    assert utils.guess_content_type_from_url("http://example.com/VIDEO.MP4") == "video/mp4"


def test_guess_extension_from_content_type():
    assert utils.guess_extension_from_content_type("image/png") == ".png"
    assert utils.guess_extension_from_content_type("unknown/type") == ""


def test_parse_s3_url_variants():
    assert utils.parse_s3_url("s3://bucket/key") == ("bucket", "key")
    assert utils.parse_s3_url("/bucket/key") == ("bucket", "key")


def test_parse_s3_url_invalid():
    with pytest.raises(ValueError):
        utils.parse_s3_url("invalid")


def test_parse_s3_url_requires_object_name():
    with pytest.raises(ValueError):
        utils.parse_s3_url("s3://bucket/")

    with pytest.raises(ValueError):
        utils.parse_s3_url("/bucket")


def test_base64_to_bytes_header_without_base64_flag():
    payload = base64.b64encode(b"json-bytes").decode("utf-8")
    decoded, content_type = utils.base64_to_bytes(
        f"data:application/json,{payload}"
    )
    assert decoded == b"json-bytes"
    assert content_type == "application/json"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (b"\x00\x00\x00 qt  " + b"\x00" * 6, "video/quicktime"),
        (b"OggS" + b"\x00" * 8, "audio/ogg"),
        (b"fLaC" + b"\x00" * 8, "audio/flac"),
        (b"\x1a\x45\xdf\xa3" + b"\x00" * 8, "video/webm"),
        (b"RIFF" + b"\x00" * 4 + b"AVI ", "video/x-msvideo"),
    ],
)
def test_detect_content_type_expanded_signatures(payload: bytes, expected: str):
    assert utils.detect_content_type_from_bytes(payload) == expected


def test_detect_content_type_mp3_frame_sync():
    payload = b"\xff\xfb" + b"\x00" * 4
    assert utils.detect_content_type_from_bytes(payload) == "audio/mpeg"


@pytest.mark.parametrize("value", ["", None])
def test_parse_s3_url_rejects_empty(value):
    with pytest.raises(ValueError):
        utils.parse_s3_url(value)  # type: ignore[arg-type]



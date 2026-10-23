import io
import sys
import unittest
from types import ModuleType
from unittest.mock import Mock, patch

from management.services.agent.icon_storage import (
    read_icon_image,
    upload_icon_image,
    validate_icon_image,
)


class IconStorageTests(unittest.TestCase):
    def setUp(self):
        client_module = ModuleType("database.client")
        client_module.minio_client = Mock()
        attachment_module = ModuleType("database.attachment_db")
        attachment_module.get_file_stream = Mock()
        module_patch = patch.dict(
            sys.modules,
            {
                "database.client": client_module,
                "database.attachment_db": attachment_module,
            },
        )
        module_patch.start()
        self.addCleanup(module_patch.stop)
        self.minio_client = client_module.minio_client
        self.get_file_stream = attachment_module.get_file_stream

    def test_rejects_non_image_content(self):
        with self.assertRaisesRegex(ValueError, "PNG, JPEG, GIF, or WebP"):
            validate_icon_image(b"not an image")

    def test_rejects_empty_content(self):
        with self.assertRaisesRegex(ValueError, "Icon file is empty"):
            validate_icon_image(b"")

    def test_rejects_oversized_content(self):
        with self.assertRaisesRegex(ValueError, "2 MB"):
            validate_icon_image(b"x" * (2 * 1024 * 1024 + 1))

    def test_accepts_supported_image_signature(self):
        self.assertEqual(validate_icon_image(b"\x89PNG\r\n\x1a\nrest"), "image/png")

    def test_accepts_other_supported_image_signatures(self):
        cases = (
            (b"\xff\xd8\xffrest", "image/jpeg"),
            (b"GIF87arest", "image/gif"),
            (b"GIF89arest", "image/gif"),
            (b"RIFF\x00\x00\x00\x00WEBP", "image/webp"),
        )
        for content, expected_type in cases:
            with self.subTest(expected_type=expected_type, content=content):
                self.assertEqual(validate_icon_image(content), expected_type)

    def test_rejects_incomplete_webp_signature(self):
        with self.assertRaisesRegex(ValueError, "PNG, JPEG, GIF, or WebP"):
            validate_icon_image(b"RIFF\x00\x00\x00\x00WEB")

    def test_upload_returns_type_and_passes_image_to_storage(self):
        content = b"\xff\xd8\xffimage"
        self.minio_client.upload_fileobj.return_value = (True, None)

        self.assertEqual(upload_icon_image(content, "icons/agent-1"), "image/jpeg")

        self.minio_client.upload_fileobj.assert_called_once()
        uploaded_stream, object_name = self.minio_client.upload_fileobj.call_args.args
        self.assertEqual(uploaded_stream.getvalue(), content)
        self.assertEqual(object_name, "icons/agent-1")

    def test_upload_rejects_storage_failure(self):
        self.minio_client.upload_fileobj.return_value = (False, "storage unavailable")

        with self.assertRaisesRegex(ValueError, "Failed to upload icon: storage unavailable"):
            upload_icon_image(b"GIF89aimage", "icons/agent-1")

    def test_upload_rejects_invalid_image_before_storage(self):
        with self.assertRaisesRegex(ValueError, "PNG, JPEG, GIF, or WebP"):
            upload_icon_image(b"invalid", "icons/agent-1")

        self.minio_client.upload_fileobj.assert_not_called()

    def test_read_returns_image_and_content_type(self):
        content = b"RIFF\x00\x00\x00\x00WEBPimage"
        self.get_file_stream.return_value = io.BytesIO(content)

        self.assertEqual(read_icon_image("icons/agent-1"), (content, "image/webp"))
        self.get_file_stream.assert_called_once_with("icons/agent-1")

    def test_read_rejects_missing_image(self):
        self.get_file_stream.return_value = None

        with self.assertRaisesRegex(FileNotFoundError, "Icon not found"):
            read_icon_image("icons/missing")

    def test_read_rejects_invalid_stored_image(self):
        self.get_file_stream.return_value = io.BytesIO(b"invalid")

        with self.assertRaisesRegex(FileNotFoundError, "Icon is invalid") as error:
            read_icon_image("icons/agent-1")

        self.assertIsInstance(error.exception.__cause__, ValueError)


if __name__ == "__main__":
    unittest.main()

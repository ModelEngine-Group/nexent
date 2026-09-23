import unittest
from management.services.agent.icon_storage import validate_icon_image


class IconStorageTests(unittest.TestCase):
    def test_rejects_non_image_content(self):
        with self.assertRaisesRegex(ValueError, "PNG, JPEG, GIF, or WebP"):
            validate_icon_image(b"not an image")

    def test_rejects_oversized_content(self):
        with self.assertRaisesRegex(ValueError, "2 MB"):
            validate_icon_image(b"x" * (2 * 1024 * 1024 + 1))

    def test_accepts_supported_image_signature(self):
        self.assertEqual(validate_icon_image(b"\x89PNG\r\n\x1a\nrest"), "image/png")


if __name__ == "__main__":
    unittest.main()

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

os.environ["OAUTH_TOKEN_ENCRYPTION_KEY"] = "abcdef0123456789abcdef0123456789"

from utils.token_encryption import _get_key, encrypt_token, decrypt_token


class TestGetKey(unittest.TestCase):
    def test_returns_32_byte_key(self):
        key = _get_key()
        self.assertEqual(len(key), 32)

    def test_missing_key_raises_value_error(self):
        import utils.token_encryption as mod

        original = mod._ENCRYPTION_KEY
        try:
            mod._ENCRYPTION_KEY = ""
            with self.assertRaises(ValueError):
                _get_key()
        finally:
            mod._ENCRYPTION_KEY = original

    def test_wrong_length_key_raises_value_error(self):
        import utils.token_encryption as mod

        original = mod._ENCRYPTION_KEY
        try:
            mod._ENCRYPTION_KEY = "short"
            with self.assertRaises(ValueError):
                _get_key()
        finally:
            mod._ENCRYPTION_KEY = original


class TestEncryptDecrypt(unittest.TestCase):
    def test_round_trip(self):
        plaintext = "ghp_abcdef1234567890"
        encrypted = encrypt_token(plaintext)
        decrypted = decrypt_token(encrypted)
        self.assertEqual(decrypted, plaintext)

    def test_round_trip_long_token(self):
        plaintext = "a" * 1000
        encrypted = encrypt_token(plaintext)
        decrypted = decrypt_token(encrypted)
        self.assertEqual(decrypted, plaintext)

    def test_round_trip_unicode(self):
        plaintext = "token-with-special-chars-!@#$%^&*()"
        encrypted = encrypt_token(plaintext)
        decrypted = decrypt_token(encrypted)
        self.assertEqual(decrypted, plaintext)

    def test_encrypt_empty_returns_empty(self):
        self.assertEqual(encrypt_token(""), "")

    def test_decrypt_empty_returns_empty(self):
        self.assertEqual(decrypt_token(""), "")

    def test_different_ciphertext_each_call(self):
        plaintext = "same-input"
        encrypted1 = encrypt_token(plaintext)
        encrypted2 = encrypt_token(plaintext)
        self.assertNotEqual(encrypted1, encrypted2)

    def test_decrypt_corrupted_data_raises(self):
        with self.assertRaises(Exception):
            decrypt_token("not-valid-base64-encrypted-data!!!")


if __name__ == "__main__":
    unittest.main()

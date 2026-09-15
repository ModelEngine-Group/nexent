"""Encrypt request, checkpoint, arguments and decisions with an operator-managed key."""

import base64
import hashlib
import hmac
import json

from cryptography.fernet import Fernet

from nexent.core.human_interaction.codec import json_copy


class PayloadCipher:
    def __init__(self, key: str):
        if not key:
            raise ValueError("HITL_ENCRYPTION_KEY is required when human interaction is enabled")
        self.fernet = Fernet(key.encode())
        self.signing_key = base64.urlsafe_b64decode(key)

    def seal(self, value):
        return self.fernet.encrypt(json.dumps(json_copy(value), ensure_ascii=False).encode()).decode()

    def open(self, value):
        return json.loads(self.fernet.decrypt(value.encode())) if value else None

    def digest(self, value):
        data = json.dumps(json_copy(value), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        return hmac.new(self.signing_key, data, hashlib.sha256).hexdigest()

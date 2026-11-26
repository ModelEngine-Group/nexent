# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Machine-local credential resolution for black-box API tests."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml


AUTOMATION = Path(__file__).resolve().parents[2] / "automation"
sys.path.insert(0, str(AUTOMATION))

from shared.auth import configured_user


class AuthConfigTests(unittest.TestCase):
    def test_process_password_overrides_machine_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            config = home / "config"
            config.mkdir()
            (config / "users.yaml").write_text(
                yaml.safe_dump({
                    "users": [{
                        "id": "tenant_a_admin",
                        "username": "fixture@example.invalid",
                        "password_env_key": "SYNTHETIC_PASSWORD",
                    }],
                }),
                encoding="utf-8",
            )
            (config / "secrets.env").write_text(
                "SYNTHETIC_PASSWORD=file-value\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {
                "NEXENT_TEST_HOME": str(home),
                "SYNTHETIC_PASSWORD": "process-value",
            }):
                _, password = configured_user("tenant_a_admin", home=home)
            self.assertEqual(password, "process-value")


if __name__ == "__main__":
    unittest.main()

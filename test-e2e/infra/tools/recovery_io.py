# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Private configuration writes, independent of any deployment executor."""
import os


def protected_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".switch-next")
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)

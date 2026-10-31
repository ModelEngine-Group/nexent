# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Container healthcheck sharing the service's configured listener port."""

from urllib.request import urlopen

from gateway.configuration import load_settings


def main():
    settings = load_settings()
    with urlopen(f"http://127.0.0.1:{settings.port}/health/ready", timeout=3) as response:
        if response.status != 200:
            raise RuntimeError("Gateway readiness failed")


if __name__ == "__main__":
    main()

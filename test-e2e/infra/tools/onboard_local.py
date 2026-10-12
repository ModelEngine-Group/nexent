"""Create missing machine-local test configuration without changing existing files."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
from urllib.parse import urlparse


REPO = Path(__file__).resolve().parents[3]
EXAMPLES = REPO / "test-e2e/infra/config"
TEMPLATES = {
    "daily.env": "daily.env.example",
    "environment.yaml": "environment.example.yaml",
    "pipeline.yaml": "pipeline.example.yaml",
    "secrets.env": "secrets.env.example",
    "users.yaml": "users.example.yaml",
    "models.yaml": "models.example.yaml",
    "test-assets.yaml": "test-assets.example.yaml",
    "asset-policy.yaml": "asset-policy.example.yaml",
    "anchor-assets.yaml": "anchor-assets.example.yaml",
}
URL_DEFAULTS = {
    "base_url": "http://localhost:3000",
    "config": "http://localhost:5010",
    "runtime": "http://localhost:5014",
    "northbound": "http://localhost:5013",
    "data_process": "http://localhost:5012",
}


def checked_home(value: Path) -> Path:
    value = value.expanduser()
    if not value.is_absolute():
        raise ValueError("Test home must be an absolute path")
    home = value.resolve()
    if home == REPO or home.is_relative_to(REPO) or REPO.is_relative_to(home):
        raise ValueError("Test home must be outside, and must not contain, the Git checkout")
    return home


def prompt_home() -> Path:
    default = REPO.parent / "nexent-test-suite"
    while True:
        entered = input(f"Test home (absolute path) [{default}]: ").strip()
        try:
            return checked_home(Path(entered) if entered else default)
        except ValueError as exc:
            print(str(exc))


def checked_url(value: str) -> str:
    value = value.rstrip("/")
    parsed = urlparse(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or
            parsed.username or parsed.password or any(char.isspace() for char in value)):
        raise ValueError("Service address must be an http(s) URL without credentials or whitespace")
    return value


def checked_host(value: str) -> str:
    if value and not re.fullmatch(r"[A-Za-z0-9_.:-]+", value):
        raise ValueError("Container host must be a host name or IP address, not a URL")
    return value


def prompt(label: str, default: str, validator) -> str:
    while True:
        entered = input(f"{label} [{default}]: ").strip() or default
        try:
            return validator(entered)
        except ValueError as exc:
            print(str(exc))


def create_content(name: str, template: str, args: argparse.Namespace, *, interactive: bool) -> str:
    if name == "environment.yaml" and (interactive or args.urls):
        urls = {}
        for key, default in URL_DEFAULTS.items():
            supplied = (args.urls or {}).get(key, default)
            label = "Frontend" if key == "base_url" else f"{key} service"
            urls[key] = prompt(label, supplied, checked_url) if interactive else checked_url(supplied)
        data = {
            "base_url": urls["base_url"], "locale": "zh-CN", "timezone": "Asia/Shanghai",
            "services": {key: {"url": urls[key]} for key in URL_DEFAULTS if key != "base_url"},
        }
        # JSON is valid YAML and needs no PyYAML during first-use setup.
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if name == "daily.env" and (interactive or args.container_host or args.mcp_container_host):
        initial = args.container_host or ("host.docker.internal" if os.name == "nt" else "172.17.0.1")
        assets_host = prompt("Product-container host for test assets", initial, checked_host) if interactive else checked_host(initial)
        mcp_initial = args.mcp_container_host or assets_host
        mcp_host = prompt("Product-container host for MCP", mcp_initial, checked_host) if interactive else checked_host(mcp_initial)
        template = re.sub(r"(?m)^NEXENT_TEST_ASSETS_CONTAINER_HOST=.*$",
                          f"NEXENT_TEST_ASSETS_CONTAINER_HOST={assets_host}", template)
        template = re.sub(r"(?m)^NEXENT_TEST_MCP_CONTAINER_HOST=.*$",
                          f"NEXENT_TEST_MCP_CONTAINER_HOST={mcp_host}", template)
    return template


def create_missing(home: Path, args: argparse.Namespace) -> list[dict[str, str]]:
    config_dir = home / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    outcome = []
    for name, source_name in TEMPLATES.items():
        destination = config_dir / name
        if destination.exists():
            outcome.append({"file": name, "status": "KEPT"})
            continue
        template = (EXAMPLES / source_name).read_text(encoding="utf-8")
        content = create_content(name, template, args, interactive=args.interactive)
        try:
            descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600 if name == "secrets.env" else 0o640)
        except FileExistsError:
            outcome.append({"file": name, "status": "KEPT"})
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(content)
        outcome.append({"file": name, "status": "CREATED"})
    return outcome


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-home", type=Path, help="Absolute machine-local directory outside this checkout")
    parser.add_argument("--execute", action="store_true", help="Create only missing configuration files")
    parser.add_argument("--interactive", action="store_true", help="Ask for new service addresses and container hosts")
    parser.add_argument("--base-url")
    parser.add_argument("--config-url")
    parser.add_argument("--runtime-url")
    parser.add_argument("--northbound-url")
    parser.add_argument("--data-process-url")
    parser.add_argument("--container-host")
    parser.add_argument("--mcp-container-host")
    args = parser.parse_args(argv)
    if args.interactive and not args.execute:
        parser.error("--interactive requires --execute")
    if not args.test_home and not args.interactive:
        parser.error("--test-home is required unless --interactive is used")
    args.urls = {key: value for key, value in {
        "base_url": args.base_url, "config": args.config_url, "runtime": args.runtime_url,
        "northbound": args.northbound_url, "data_process": args.data_process_url,
    }.items() if value is not None}
    try:
        home = checked_home(args.test_home) if args.test_home else prompt_home()
        if args.execute:
            rows = create_missing(home, args)
        else:
            rows = [{"file": name, "status": "KEPT" if (home / "config" / name).exists() else "WOULD_CREATE"}
                    for name in TEMPLATES]
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps({"test_home": str(home), "applied": args.execute, "files": rows}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Read-only checks for the selected machine-local Nexent test configuration."""

from __future__ import annotations

import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import build_opener, ProxyHandler

import yaml


ENV_LINE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
SERVICES = ("config", "runtime", "northbound", "data_process")


def env_file(path: Path) -> tuple[dict[str, str], list[str]]:
    values: dict[str, str] = {}
    problems: list[str] = []
    if not path.is_file():
        return values, [f"missing machine config: {path.name}"]
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = ENV_LINE.fullmatch(line)
        if not match:
            problems.append(f"invalid {path.name} line {number}")
            continue
        key, value = match.groups()
        if key in values:
            problems.append(f"duplicate {path.name} key {key}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key] = value
    return values, problems


def yaml_file(path: Path) -> tuple[dict, list[str]]:
    if not path.is_file():
        return {}, [f"missing machine config: {path.name}"]
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}, [f"invalid YAML in {path.name}"]
    if not isinstance(value, dict):
        return {}, [f"{path.name} must be a mapping"]
    return value, []


def valid_url(value: object) -> bool:
    if not isinstance(value, str) or any(char.isspace() for char in value):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not parsed.username and not parsed.password


def static_config_problems(home: Path, records: list[dict]) -> list[str]:
    config = home / "config"
    daily, problems = env_file(config / "daily.env")
    _, errors = env_file(config / "secrets.env")
    problems.extend(errors)
    environment, errors = yaml_file(config / "environment.yaml")
    problems.extend(errors)
    if environment:
        if not valid_url(environment.get("base_url")):
            problems.append("environment.yaml base_url must be an http(s) URL without credentials")
        services = environment.get("services")
        for name in SERVICES:
            entry = services.get(name) if isinstance(services, dict) else None
            if not isinstance(entry, dict) or not valid_url(entry.get("url")):
                problems.append(f"environment.yaml services.{name}.url is missing or invalid")
    if os.name != "nt" and (config / "secrets.env").is_file():
        if (config / "secrets.env").stat().st_mode & 0o077:
            problems.append("secrets.env must not be readable by group or others")

    online = [record for record in records if record["stage"] != "D1" and record["status"] == "active"]
    if online:
        loaded = {}
        for name in ("users.yaml", "models.yaml", "test-assets.yaml", "asset-policy.yaml", "anchor-assets.yaml"):
            loaded[name], errors = yaml_file(config / name)
            problems.extend(errors)
        users, models = loaded["users.yaml"], loaded["models.yaml"]
        for filename, data, collection in (
            ("users.yaml", users, "users"),
            ("models.yaml", models, "models"),
        ):
            rows = data.get(collection, [])
            if not isinstance(rows, list):
                problems.append(f"{filename} {collection} must be a list")
                continue
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    problems.append(f"{filename} {collection}[{index}] must be a mapping")
                    continue
                # Optional profiles may deliberately have no local credential.
                # A selected Case's asset helper checks its actual credential.
                if row.get("username") == "replace-me" or row.get("provider") == "replace-me":
                    problems.append(f"{filename} {collection}[{index}] still has a placeholder")
        anchors = any((record.get("execution") or {}).get("preparation", {}).get("anchors") for record in online)
        if anchors:
            for name in ("NEXENT_TEST_ASSETS_CONTAINER_HOST", "NEXENT_TEST_MCP_CONTAINER_HOST"):
                if not daily.get(name):
                    problems.append(f"daily.env {name} is required by selected anchored cases")
    return sorted(set(problems))


def live_service_problems(home: Path) -> list[str]:
    environment, errors = yaml_file(home / "config/environment.yaml")
    if errors:
        return errors
    urls = {"frontend": environment.get("base_url")}
    services = environment.get("services") or {}
    for name in SERVICES:
        entry = services.get(name) if isinstance(services, dict) else None
        urls[name] = entry.get("url") if isinstance(entry, dict) else None
    opener = build_opener(ProxyHandler({}))
    problems = []
    for name, url in urls.items():
        if not valid_url(url):
            continue
        try:
            with opener.open(url, timeout=5) as response:
                if response.status >= 500:
                    problems.append(f"{name} returned HTTP {response.status}")
        except HTTPError as exc:
            if exc.code >= 500:
                problems.append(f"{name} returned HTTP {exc.code}")
        except (OSError, URLError, TimeoutError):
            problems.append(f"{name} is not reachable from this host")
    return problems

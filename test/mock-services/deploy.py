#!/usr/bin/env python3
"""Deploy registered mock stacks with Python's standard library and Docker Compose."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = Path(__file__).resolve().parent
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class DeploymentError(RuntimeError):
    pass


def repo_file(value: str, root: Path = ROOT) -> Path:
    if not isinstance(value, str) or Path(value).is_absolute() or re.match(r"^[A-Za-z]:", value):
        raise DeploymentError("Registration paths must be repository-relative")
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise DeploymentError(f"Missing or out-of-repository file: {value}")
    return path


def registrations(directory: Path = REGISTRY, root: Path = ROOT) -> dict:
    registry = {}
    for path in sorted(directory.glob("*/deployment.json")):
        spec = json.loads(path.read_text(encoding="utf-8"))
        allowed = {"schema_version", "id", "aliases", "project", "compose_files", "product_network_files", "services", "oneshot_services", "networks", "readiness"}
        if set(spec) - allowed or spec.get("schema_version") != 1:
            raise DeploymentError(f"Invalid registration fields/version: {path}")
        for key in ("id", "project"):
            if not isinstance(spec.get(key), str) or not NAME.fullmatch(spec[key]):
                raise DeploymentError(f"Invalid {key}: {path}")
        for key in ("compose_files", "services", "readiness"):
            if not isinstance(spec.get(key), list) or not spec[key]:
                raise DeploymentError(f"Non-empty {key} is required: {path}")
        for key in ("aliases", "product_network_files", "networks", "oneshot_services"):
            if not isinstance(spec.get(key, []), list):
                raise DeploymentError(f"{key} must be a list: {path}")
        for file in spec["compose_files"] + spec.get("product_network_files", []):
            repo_file(file, root)
        for name in spec["services"] + spec.get("networks", []):
            if not isinstance(name, str) or not NAME.fullmatch(name):
                raise DeploymentError(f"Invalid service/network name: {path}")
        if any(name not in spec["services"] for name in spec.get("oneshot_services", [])):
            raise DeploymentError(f"One-shot services must belong to services: {path}")
        for probe in spec["readiness"]:
            if not isinstance(probe, dict) or set(probe) - {"url", "json_equals"}:
                raise DeploymentError(f"Invalid readiness check: {path}")
            url = probe.get("url", "")
            if not isinstance(url, str) or not url.startswith(("http://127.0.0.1:", "http://localhost:")):
                raise DeploymentError(f"Readiness URL must target a local published port: {path}")
            if not isinstance(probe.get("json_equals", {}), dict):
                raise DeploymentError(f"json_equals must be a mapping: {path}")
        for alias in [spec["id"], *spec.get("aliases", [])]:
            if not isinstance(alias, str) or not NAME.fullmatch(alias) or alias in registry:
                raise DeploymentError(f"Invalid or duplicate service alias: {alias}")
            registry[alias] = spec
    return registry


def run(command: list[str], *, env=None, capture=False, check=True):
    result = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=capture, check=False)
    if check and result.returncode:
        raise DeploymentError(f"Command failed ({result.returncode}): {' '.join(command)}")
    return result


def compose_cli() -> list[str]:
    for command in (["docker", "compose"], ["docker-compose"]):
        try:
            if run([*command, "version"], capture=True, check=False).returncode == 0:
                return list(command)
        except FileNotFoundError:
            continue
    raise DeploymentError("Docker Compose is required (docker compose or docker-compose)")


def compose_command(spec, args, cli):
    project = args.project or spec["project"]
    if not NAME.fullmatch(project):
        raise DeploymentError("Invalid Compose project name")
    files = list(spec["compose_files"])
    if not args.standalone:
        files.extend(spec.get("product_network_files", []))
    first = repo_file(files[0])
    command = [*cli, "--project-name", project, "--project-directory", str(first.parent)]
    if args.env_file:
        env_file = Path(args.env_file).resolve()
        if not env_file.is_file():
            raise DeploymentError("--env-file does not exist")
        command.extend(["--env-file", str(env_file)])
    for file in files:
        command.extend(["-f", str(repo_file(file))])
    return command


def action_command(base, spec, args):
    if args.action == "up":
        tail = ["up", "-d"] + ([] if args.no_build else ["--build"])
    elif args.action == "stop":
        tail = ["stop"]
    elif args.action == "logs":
        tail = ["logs", "--no-color", "--tail", "200"]
    else:
        tail = ["ps", "-a"]
    # Never use project-wide down, volume deletion, pruning or orphan removal.
    return [*base, *tail, *spec["services"]]


def network_exists(name, env):
    return run(["docker", "network", "inspect", name], env=env, capture=True, check=False).returncode == 0


def probe_ready(probe, timeout=5):
    # Ignore machine proxy settings for local health probes. Never send secrets.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(probe["url"], headers={"User-Agent": "nexent-mock-deployer"})
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200:
                return False
            checks = probe.get("json_equals", {})
            if not checks:
                return True
            body = json.load(response)
            for key, expected in checks.items():
                actual = body
                for part in key.split("."):
                    if not isinstance(actual, dict) or part not in actual:
                        return False
                    actual = actual[part]
                if type(actual) is not type(expected) or actual != expected:
                    return False
            return True
    except (OSError, ValueError, urllib.error.URLError):
        return False


def owned_containers_running(base, spec, env):
    result = run([*base, "ps", "-a", "-q", *spec["services"]], env=env, capture=True)
    ids = result.stdout.split()
    if not ids:
        return False
    result = run(["docker", "inspect", *ids], env=env, capture=True)
    states = {item["Config"]["Labels"].get("com.docker.compose.service"): item["State"] for item in json.loads(result.stdout)}
    for service in spec["services"]:
        state = states.get(service, {})
        if service in spec.get("oneshot_services", []):
            if state.get("Status") != "exited" or state.get("ExitCode") != 0:
                return False
        elif not state.get("Running"):
            return False
    return True


def wait_ready(base, spec, env, timeout):
    deadline, last_notice = time.monotonic() + timeout, 0.0
    while True:
        now = time.monotonic()
        if now >= deadline:
            raise DeploymentError("Readiness timeout; containers are retained for diagnosis. Use the logs command.")
        checks = [probe_ready(probe, timeout=max(0.1, min(5, deadline-time.monotonic()))) for probe in spec["readiness"]]
        if all(checks) and owned_containers_running(base, spec, env):
            print(f"READY: {spec['id']} (service readiness and Compose container state verified)")
            return
        if now - last_notice >= 15:
            print(f"Waiting for {spec['id']}: {sum(checks)}/{len(checks)} readiness checks passed", flush=True)
            last_notice = now
        time.sleep(min(2, max(0, deadline-time.monotonic())))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("list", "up", "status", "logs", "stop"))
    parser.add_argument("service", nargs="?", help="Registered service ID or alias (case-insensitive)")
    parser.add_argument("--project", help="Explicit existing Compose project to reuse")
    parser.add_argument("--standalone", action="store_true", help="Do not attach to the product network")
    parser.add_argument("--product-network", default=os.getenv("NEXENT_PRODUCT_NETWORK", "nexent_network"))
    parser.add_argument("--env-file", help="Explicit local Compose env file; never modified")
    parser.add_argument("--timeout", type=int, default=180, help="Readiness wait seconds after Compose up")
    parser.add_argument("--no-build", action="store_true", help="Reuse existing images")
    parser.add_argument("--dry-run", action="store_true", help="Validate registration and show commands without Docker access")
    args = parser.parse_args(argv)
    try:
        registry = registrations()
        if args.action == "list":
            for spec in {value["id"]: value for value in registry.values()}.values():
                print(f"{spec['id']} (aliases: {', '.join(spec.get('aliases', []))})")
            return 0
        if not args.service or args.service.lower() not in registry:
            raise DeploymentError("Unknown service; use 'list' to see registered services")
        if args.timeout <= 0 or not NAME.fullmatch(args.product_network):
            raise DeploymentError("Positive timeout and valid product network name are required")
        spec = registry[args.service.lower()]
        cli = ["docker", "compose"] if args.dry_run else compose_cli()
        base = compose_command(spec, args, cli)
        command = action_command(base, spec, args)
        if args.dry_run:
            print(json.dumps({"command": command, "mock_networks": spec.get("networks", []), "required_product_network": None if args.standalone else args.product_network, "readiness": spec["readiness"]}, indent=2))
            return 0
        env = dict(os.environ, NEXENT_PRODUCT_NETWORK=args.product_network)
        run(["docker", "info"], env=env, capture=True)
        run([*base, "config", "--quiet"], env=env)
        if args.action == "up":
            if not args.standalone and spec.get("product_network_files") and not network_exists(args.product_network, env):
                raise DeploymentError("Product network is missing; supply --product-network or use --standalone. Product deployment is never started automatically.")
            for network in spec.get("networks", []):
                if not network_exists(network, env):
                    run(["docker", "network", "create", network], env=env)
        run(command, env=env)
        if args.action == "up":
            wait_ready(base, spec, env, args.timeout)
        elif args.action == "status":
            healthy = all(probe_ready(probe) for probe in spec["readiness"]) and owned_containers_running(base, spec, env)
            print("READY" if healthy else "NOT READY")
            return 0 if healthy else 1
        return 0
    except (DeploymentError, OSError, ValueError) as exc:
        print(f"Mock deployment failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted; no containers or volumes were removed.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

"""Resolve the local product deployment's Compose inputs without copying secrets.

The product setup keeps non-image settings in deploy/env/.env and generated
image tags in deploy/docker/.env.generated.  Docker Compose does not discover
either file when tests invoke a compose file from a different cwd.
"""

from __future__ import annotations

from shared.config import repo_root


def product_compose_args(project: str) -> list[str]:
    root = repo_root()
    base_env = root / "deploy" / "env" / ".env"
    image_env = root / "deploy" / "docker" / ".env.generated"
    compose = root / "deploy" / "docker" / "compose" / "docker-compose.yml"
    missing = [str(path) for path in (base_env, image_env, compose) if not path.is_file()]
    if missing:
        raise RuntimeError("local product Compose inputs are missing: " + ", ".join(missing))
    return [
        "compose", "--env-file", str(base_env), "--env-file", str(image_env),
        "-p", project, "-f", str(compose),
    ]

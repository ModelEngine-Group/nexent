# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Run the owned storage probe inside an actual Runtime container."""

from contextlib import closing
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
from uuid import UUID, uuid5

from backend.http.logging import HybridRotatingFileHandler
from contracts.constants.environment import (
    AGENT_WORKSPACE_ROOT,
    CONTAINER_SKILLS_PATH,
    LOG_DIR,
    MEMORY_PROVIDER_PLUGINS_DIR,
    MINIO_ENDPOINT,
)
from infrastructure.object_storage.client import minio_client
from nexent.core.agents.resources.workspace import cleanup_run_workspace
from nexent.core.tools.upload_to_s3_tool import UploadToS3Tool


MOUNTS = {
    "workspace": Path("/mnt/nexent"),
    "skills": Path("/mnt/nexent-data/skills"),
    "plugins": Path("/mnt/nexent-data/memory-provider-plugins"),
    "logs": Path("/mnt/nexent-data/logs"),
}
FILENAME = "artifact.txt"
SETTINGS_NAME = "storage-probe"
PLUGIN_SOURCE = ("# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.\n"
                 "class StorageProbeProvider:\n"
                 "    def search(self, query):\n"
                 "        return []\n").encode()


def token_run_id(token, role):
    return uuid5(UUID(hex=token), role).hex


def digest(path):
    if path != path.resolve():
        raise RuntimeError("Storage fixture must not follow symlinks")
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def payload(token, role, stream):
    return f"{token}:{role}:{stream}\n".encode()


def configured_roots():
    mountpoints = {line.split()[4] for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()}
    roots = {"workspace": Path(AGENT_WORKSPACE_ROOT), "skills": Path(CONTAINER_SKILLS_PATH or ""),
             "plugins": Path(MEMORY_PROVIDER_PLUGINS_DIR), "logs": Path(LOG_DIR)}
    pod = os.environ.get("POD_NAME")
    if not pod or roots["logs"] != MOUNTS["logs"] / pod:
        raise RuntimeError("Runtime LOG_DIR must be scoped to the current Pod")
    for name, mount in MOUNTS.items():
        root = roots[name]
        if str(mount) not in mountpoints or root != root.resolve() or not root.is_relative_to(mount):
            raise RuntimeError(f"Runtime {name} is not inside the expected mounted filesystem")
    return roots


def workspace(roots, token, role):
    from runtime.workspace import create_run_workspace

    path = Path(create_run_workspace(token, token_run_id(token, role), workspace_root=roots["workspace"]))
    if path != path.resolve():
        raise RuntimeError("Run workspace fixture must not follow symlinks")
    return path


def role_file(roots, name, token, role):
    return roots[name] / f".nexent-storage-d3-{token}" / f"{role}.txt"


def output(roots, token, role):
    return workspace(roots, token, role) / "outputs" / FILENAME


def keep_file(roots, token):
    return roots["workspace"] / token / "keep.txt"


def write_exclusive(path, content):
    if path.parent != path.parent.resolve():
        raise RuntimeError("Storage fixture path must stay within its volume")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(content)


def plugin_manifest(token):
    return json.dumps({
        "name": SETTINGS_NAME, "version": "1.0.0", "entry_point": "provider.py",
        "class_name": "StorageProbeProvider", "implements": ["searchable"], "description": token,
    }).encode()


def seed_settings(roots, token):
    skill_file = roots["skills"] / token / SETTINGS_NAME / "config" / "config.yaml"
    write_exclusive(skill_file, json.dumps({"revision": token}).encode())
    plugin_dir = roots["plugins"] / f".nexent-storage-settings-{token}" / SETTINGS_NAME
    write_exclusive(plugin_dir / "provider.py", PLUGIN_SOURCE)
    write_exclusive(plugin_dir / "plugin.yaml", plugin_manifest(token))


def read_settings(roots, token):
    config = roots["skills"] / token / SETTINGS_NAME / "config" / "config.yaml"
    if config != config.resolve():
        raise RuntimeError("Expected the owned Skill configuration")
    skill = json.loads(config.read_bytes())
    plugins_root = roots["plugins"] / f".nexent-storage-settings-{token}"
    plugin_dirs = [path for path in plugins_root.iterdir() if path.is_dir()]
    if plugin_dirs != [plugins_root / SETTINGS_NAME]:
        raise RuntimeError("Unexpected entries in the dedicated plugin fixture directory")
    for filename, expected in (("provider.py", PLUGIN_SOURCE), ("plugin.yaml", plugin_manifest(token))):
        path = plugins_root / SETTINGS_NAME / filename
        if path != path.resolve() or path.read_bytes() != expected:
            raise RuntimeError("Refusing to load a plugin other than the owned fixture")
    plugin_data = json.loads((plugins_root / SETTINGS_NAME / "plugin.yaml").read_bytes())
    return {"skill_revision": skill["revision"], "plugin_revision": plugin_data["description"],
            "plugin_version": plugin_data["version"]}


def verify_management_settings(token):
    from management.services.memory.providers.plugins import PluginLoader
    from management.services.skill.local_config import SkillConfigPaths
    from management.services.skill.params import _parse_skill_params_from_config_bytes
    from management.services.skill.yaml_cache import skill_yaml_cache

    roots = {"skills": Path(CONTAINER_SKILLS_PATH), "plugins": Path(MEMORY_PROVIDER_PLUGINS_DIR)}
    receipt = read_settings(roots, token)
    path_context = SkillConfigPaths(str(roots["skills"] / token))
    (config, exists), _ = path_context.files_for(SETTINGS_NAME)
    assert exists and skill_yaml_cache.load(config, _parse_skill_params_from_config_bytes)["revision"] == token
    plugins_root = roots["plugins"] / f".nexent-storage-settings-{token}"
    plugin = PluginLoader(str(plugins_root)).get_plugin(SETTINGS_NAME)
    assert plugin is not None and (plugin.description, plugin.version) == (token, "1.0.0")
    return receipt


def seed(roots, token, role):
    write_exclusive(output(roots, token, role), payload(token, role, "output"))
    for name in ("skills", "plugins"):
        write_exclusive(role_file(roots, name, token, role), payload(token, role, name))
    if role == "a":
        write_exclusive(keep_file(roots, token), payload(token, role, "non-run"))
        seed_settings(roots, token)
    return snapshot(roots, token, role)


def snapshot(roots, token, role):
    return {"output": digest(output(roots, token, role)), "keep": digest(keep_file(roots, token)),
            "settings": read_settings(roots, token),
            **{name: digest(role_file(roots, name, token, role)) for name in ("skills", "plugins")}}


def object_name(token, role):
    return f"workspace/{token}/{token_run_id(token, role)}/outputs/{FILENAME}"


def require_owned_storage():
    endpoint = urlsplit(MINIO_ENDPOINT or "")
    if (endpoint.scheme not in {"http", "https"} or endpoint.port != 9000
            or endpoint.hostname not in {"nexent-minio", "nexent-minio.nexent", "nexent-minio.nexent.svc",
                                         "nexent-minio.nexent.svc.cluster.local"}):
        raise RuntimeError("Refusing to use an object store outside the owned Kubernetes release")


def upload(roots, token, role):
    require_owned_storage()
    tool = UploadToS3Tool(workspace_path=str(workspace(roots, token, role)), minio_client=minio_client,
                         user_id=token, tenant_id=token, run_id=token_run_id(token, role))
    result = json.loads(tool.forward(FILENAME))
    if result.get("status") != "success" or result.get("object_name") != object_name(token, role):
        raise RuntimeError("Product storage tool did not write the expected run-scoped object")
    return result["size"]


def download(roots, token, role):
    require_owned_storage()
    success, stream = minio_client.get_file_stream(object_name(token, role))
    if not success:
        raise RuntimeError("The peer Runtime could not read the run-scoped object")
    with closing(stream):
        return hashlib.sha256(stream.read(4096)).hexdigest()


def read_attachment(user_id, tenant_id, object_name):
    from management.services.agent.preparation.inputs import _validate_run_minio_files

    require_owned_storage()
    if not object_name.startswith("attachments/") or len(object_name.split("/")) < 3:
        raise ValueError("Expected a run-owned attachment object")
    try:
        _validate_run_minio_files([{"object_name": object_name, "name": "fixture.txt"}], user_id, tenant_id)
    except PermissionError:
        return {"status": "denied"}
    success, stream = minio_client.get_file_stream(object_name)
    if not success:
        raise RuntimeError("Runtime could not read the authenticated attachment")
    with closing(stream):
        return {"status": "read", "sha256": hashlib.sha256(stream.read(4096)).hexdigest()}


def live_attachment_snapshot(token, roots, identity="owner", expected_run_id=None):
    from sqlalchemy import select

    from infrastructure.rdb.agent_execution import AgentExecution
    from infrastructure.rdb.client import get_db_session

    if identity not in {"owner", "foreign"} or (
        expected_run_id is not None and UUID(hex=expected_run_id).hex != expected_run_id
    ):
        raise ValueError("Expected a case-owned identity and Run UUID")
    owner = str(uuid5(UUID(hex=token), f"{identity}:user"))
    tenant = str(uuid5(UUID(hex=token), f"{identity}:tenant"))
    with get_db_session() as session:
        execution = session.scalars(select(AgentExecution).where(
            AgentExecution.tenant_id == tenant,
            AgentExecution.created_by == owner,
            AgentExecution.delete_flag == "N",
        )).one()
        state = {"execution_id": execution.run_id, "conversation_id": execution.conversation_id,
                 "owner": execution.owner_id, "status": execution.status}
    owner_root = roots["workspace"] / owner
    if expected_run_id is not None:
        run_path = owner_root / expected_run_id
        state["workspace_exists"] = run_path.exists() or run_path.is_symlink()
    attachments = list(owner_root.glob("*/inputs/000_runtime-input.txt"))
    if not attachments:
        return {**state, "run_id": None, "sha256": None}
    attachment, = attachments
    run_id = attachment.parents[1].name
    if UUID(hex=run_id).hex != run_id or run_id != state["execution_id"]:
        raise RuntimeError("Expected one Run-scoped attachment workspace")
    return {**state, "run_id": run_id, "sha256": digest(attachment)}


def finish(roots, token, role):
    return cleanup_run_workspace(str(workspace(roots, token, role)), token_run_id(token, role))


def rotate(roots, token, role):
    log_path = roots["logs"] / f".nexent-storage-d3-{token}.log"
    write_exclusive(log_path, b"")
    handler = HybridRotatingFileHandler(log_path, when="midnight", maxBytes=1, backupCount=1, encoding="utf-8")
    try:
        for sequence in ("before", "after"):
            message = payload(token, role, sequence).decode().rstrip()
            handler.handle(logging.LogRecord("runtime-storage-d3", logging.INFO, __file__, 1, message, (), None))
    finally:
        handler.close()
    rotated, = log_path.parent.glob(f"{log_path.name}.*")
    return {"directory": str(log_path.parent), "rotated": digest(rotated), "current": digest(log_path)}


def main():
    action, token, role, *extra = sys.argv[1:]
    if UUID(hex=token).hex != token or role not in {"a", "b"}:
        raise ValueError("Expected an owned fixture token and Runtime role")
    actions = {"seed": seed, "snapshot": snapshot, "upload": upload, "download": download,
               "finish": finish, "rotate": rotate}
    if action == "read-attachment":
        record = read_attachment(*extra)
    elif action == "verify-settings":
        record = verify_management_settings(token)
    elif action == "live-attachment":
        record = live_attachment_snapshot(token, configured_roots(), *extra)
    else:
        if extra:
            raise ValueError("Unexpected arguments to the Runtime storage probe")
        record = actions[action](configured_roots(), token, role)
    print("D3_STORAGE " + json.dumps(record, sort_keys=True))


if __name__ == "__main__":
    main()

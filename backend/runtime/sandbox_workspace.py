# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Trusted Runtime preparation for a sandbox's owner-only RWX subtree."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import threading
from pathlib import Path

from nexent.core.agents.sandbox_contracts import SandboxOwner


def _business_key(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ValueError('Workspace business identity must be a bounded nonempty string')
    return hashlib.sha256(value.encode()).hexdigest()


def _no_symlinks(path: Path) -> None:
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError('Workspace symlink ancestor is forbidden')


class KubernetesWorkspace:
    def __init__(self, root: str | Path, owner: SandboxOwner, *, execution_gid: int):
        root = Path(root).absolute()
        _no_symlinks(root)
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,252}', owner.pod_uid):
            raise ValueError('Invalid owner UID path component')
        if type(execution_gid) is not int or execution_gid < 0:
            raise ValueError('Invalid sandbox execution group')
        self.root, self.owner, self.execution_gid = root, owner, execution_gid
        self.owner_root = root / 'owners' / owner.pod_uid
        # This subtree is not included in any sandbox volumeMount.
        self.control_root = root / '.sandbox-control'
        self._stage_lock = threading.Lock()

    def run_path(self, tenant_id: str, user_id: str, run_id: str) -> Path:
        if not isinstance(run_id, str) or not re.fullmatch(r'[a-f0-9]{32}', run_id):
            raise ValueError('Invalid internal execution run ID')
        return self.owner_root / _business_key(tenant_id) / _business_key(user_id) / run_id

    def volume_subpath(self, volume_mount: str | Path) -> str:
        """The deployment supplies the Runtime PVC mount, never model policy."""
        mount = Path(volume_mount).absolute()
        _no_symlinks(mount)
        return self.owner_root.relative_to(mount).as_posix()

    def _directory(self, path: Path, mode: int) -> None:
        _no_symlinks(path)
        path.mkdir(parents=True, exist_ok=True)
        _no_symlinks(path)
        if not path.is_dir():
            raise ValueError('Workspace path is not a directory')
        # On Windows this is a development path check, never POSIX permission proof.
        if os.name == 'posix':
            if os.geteuid() != 0:
                raise RuntimeError('Kubernetes workspace preparation requires a trusted root Runtime')
            os.chown(path, 0, self.execution_gid, follow_symlinks=False)
            path.chmod(mode, follow_symlinks=False)

    def prepare_run(self, tenant_id: str, user_id: str, run_id: str) -> Path:
        run = self.run_path(tenant_id, user_id, run_id)
        # All ancestors are Runtime-owned and nonwritable to the business UID.
        for parent in reversed((run, *run.parents)):
            if parent == self.root or parent.is_relative_to(self.root):
                # Preserve a preflighted PVC mount root's setgid/group access
                # when the workspace root is configured as that mount itself.
                mode = 0o750
                if parent == self.root and parent.exists() and parent.stat().st_mode & 0o2000:
                    mode |= 0o2070
                self._directory(parent, mode)
        for name in ('inputs', '.skills'):
            self._directory(run / name, 0o750)
        for name in ('outputs', 'tmp'):
            self._directory(run / name, 0o2770)
        return run

    def seal_materials(self, run: Path) -> None:
        """Seal trusted inputs/Skill copies; never chmod the writable output tree."""
        run.relative_to(self.owner_root)
        _no_symlinks(run)
        for name in ('inputs', '.skills', 'skills', '.skill_snapshot'):
            material = run / name
            if not material.exists():
                continue
            for path in (material, *material.rglob('*')):
                _no_symlinks(path)
                if os.name == 'posix':
                    os.chown(path, 0, self.execution_gid, follow_symlinks=False)
                    path.chmod(0o550 if path.is_dir() else 0o440, follow_symlinks=False)

    def stage_skill(self, source: str, run: str, invocation: str) -> Path:
        """Copy original materials through the trusted Runtime, never root exec."""
        if not re.fullmatch(r'[a-f0-9]{24}', invocation):
            raise ValueError('Invalid Skill invocation identity')
        run_path = Path(run).absolute()
        run_path.relative_to(self.owner_root)
        if not re.fullmatch(r'[a-f0-9]{32}', run_path.name):
            raise ValueError('Invalid Skill run workspace')
        original = Path(source).absolute()
        _no_symlinks(original)
        if not original.is_dir():
            raise ValueError('Skill source is not a directory')
        entries = list(original.rglob('*'))
        for path in entries:
            _no_symlinks(path)
            if not path.is_dir() and not path.is_file():
                raise ValueError('Skill contains a special file')
        identity = hashlib.sha256(str(original).encode())
        for path in sorted(entries):
            info = path.stat()
            identity.update(f'{path.relative_to(original)}:{info.st_size}:{info.st_mtime_ns}'.encode())
        target = run_path / 'skills' / invocation / identity.hexdigest()[:24]
        with self._stage_lock:
            _no_symlinks(target)
            if target.exists():
                return target
            self._directory(target.parent.parent, 0o750)
            self._directory(target.parent, 0o750)
            shutil.copytree(original, target, symlinks=False)
            for path in (target, *target.rglob('*')):
                _no_symlinks(path)
                executable = bool(path.stat().st_mode & 0o111)
                if path.is_file() and path.suffix.lower() == '.sh':
                    path.write_bytes(path.read_bytes().replace(b'\r\n', b'\n'))
                if os.name == 'posix':
                    os.chown(path, 0, self.execution_gid, follow_symlinks=False)
                    path.chmod(0o550 if path.is_dir() or executable else 0o440, follow_symlinks=False)
        return target

    def cleanup_skills(self, run: str, invocation: str) -> None:
        run_path = Path(run).absolute()
        run_path.relative_to(self.owner_root)
        if not re.fullmatch(r'[a-f0-9]{32}', run_path.name) or not re.fullmatch(r'[a-f0-9]{24}', invocation):
            raise ValueError('Invalid Skill cleanup identity')
        target = run_path / 'skills' / invocation
        _no_symlinks(target)
        if target.exists():
            shutil.rmtree(target)

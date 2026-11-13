# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Existing script planning with RWX preparation and nonroot Kubernetes exec."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from nexent.core.agents.sandbox.execution import SandboxSkillScriptRunner
from nexent.core.agents.sandbox_kubernetes_exec import KubernetesProcessAdapter


_PREPARE_STORE = """import os, shutil, sys
from pathlib import Path
key = sys.argv[1]
assert len(key) == 24 and all(c in '0123456789abcdef' for c in key)
base = Path('/tmp/nexent-pnpm-stores')
if base.is_symlink():
    raise RuntimeError('Unsafe pnpm store parent')
base.mkdir(mode=0o700, exist_ok=True)
target = base / key
if target.is_symlink():
    raise RuntimeError('Unsafe pnpm store')
if not target.exists():
    source = Path('/opt/nexent/pnpm-store')
    if (source / 'v3').is_dir():
        shutil.copytree(source, target)
        for item in target.rglob('*'):
            if item.is_symlink():
                raise RuntimeError('Unsafe pnpm seed')
            item.chmod(0o700 if item.is_dir() else 0o600)
        target.chmod(0o700)
    else:
        target.mkdir(mode=0o700)
"""


@dataclass(frozen=True)
class _ProcessOutput:
    exit_code: int
    output: bytes | tuple[bytes, bytes]


class KubernetesSkillScriptRunner(SandboxSkillScriptRunner):
    def __init__(self, executor, *, workspace_access, **kwargs):
        super().__init__(executor, **kwargs)
        self._access = workspace_access
        self._host_workspace = kwargs['workspace_path']
        connection = executor._container_executor
        self._process = KubernetesProcessAdapter(
            connection.backend, connection.owner, connection.profile, connection.generation,
            check_cancelled=executor._check_execution_cancelled,
            run_lifecycle=getattr(executor, '_runtime_lifecycle', None),
        )
        self._invocation = hashlib.sha256(executor.kernel_id.encode()).hexdigest()[:24]
        self._root = f'{self._workspace_path}/skills/{self._invocation}'

    @property
    def available(self):
        return getattr(self._executor, '_nexent_backend', None) == 'kubernetes'

    def _execute_process(self, command, **kwargs):
        if kwargs.get('user', 'sandbox') not in ('sandbox', '1000'):
            raise PermissionError('Kubernetes scripts cannot request root or another execution user')
        result = self._process.run(
            command, cwd=kwargs.get('workdir', self._workspace_path), env=kwargs.get('environment', {}),
            timeout_seconds=self._timeout_seconds + 3,
        )
        return _ProcessOutput(result.exit_code, (result.stdout, result.stderr) if kwargs.get('demux')
                              else result.stdout + result.stderr)

    def _resolve_skills_root(self, working_directory):
        if (working_directory or self._workspace_path).rstrip('/') != self._workspace_path:
            raise RuntimeError('Skill script workspace does not match the sandbox runner workspace')
        return self._root

    def _stage_skill(self, manager, skill_name, script_path, tenant_id, skills_root):
        source, script, normalized = manager.resolve_skill_script(skill_name, script_path, tenant_id=tenant_id)
        relative = Path(script).resolve().relative_to(Path(source).resolve())
        staged = self._stage_skill_directory(source, skill_name, skills_root)
        return f'{staged}/{relative.as_posix()}', normalized

    def _stage_skill_directory(self, local_skill_dir, skill_name, skills_root):
        if skills_root != self._root:
            raise ValueError('Invalid Skill staging root')
        host = self._access.stage_skill(local_skill_dir, self._host_workspace, self._invocation)
        return str(self._workspace_mapping.to_container(host))

    def _normalize_staged_shell(self, script):
        # Runtime preparation already normalized its private staging copy.
        return None

    def _ensure_output_directory(self, output_dir):
        if output_dir != self._workspace_path + '/outputs':
            raise ValueError('Invalid script output directory')
        result = self._execute_process(['test', '-w', output_dir])
        if result.exit_code:
            raise PermissionError('Sandbox outputs directory is not writable')

    def _resolve_network_pnpm_store(self, workspace_dir):
        key = hashlib.sha256((workspace_dir + ':' + self._invocation).encode()).hexdigest()[:24]
        self._pnpm_store_path = '/tmp/nexent-pnpm-stores/' + key
        return self._pnpm_store_path

    def _ensure_network_pnpm_store(self, workspace_dir):
        path = self._resolve_network_pnpm_store(workspace_dir)
        if not self._pnpm_store_seeded:
            result = self._execute_process(['python', '-c', _PREPARE_STORE, path.rsplit('/', 1)[1]])
            if result.exit_code != 0:
                raise RuntimeError('Failed to prepare nonroot pnpm store')
            self._pnpm_store_seeded = True

    def cleanup(self):
        self._access.cleanup_skills(self._host_workspace, self._invocation)
        if self._pnpm_store_path:
            self._execute_process(['rm', '-rf', '--', self._pnpm_store_path])

# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Kubernetes exec transport; never retry a command whose effects are unknown."""

from __future__ import annotations

import json
import math
import time
from pathlib import PurePosixPath
from typing import Mapping, Sequence

from kubernetes.stream import stream

from nexent.core.agents.sandbox_contracts import ScriptProcessResult
from nexent.core.agents.sandbox_kubernetes import _document


# Only the remote process reads its inherited execution environment. Deployment
# configuration is injected into the SDK and is never read from the host here.
_EXEC = """import json, os, sys
p = json.loads(sys.argv[1])
os.chdir(p['cwd'])
env = dict(os.environ)
env.update(p['env'])
os.execvpe(p['argv'][0], p['argv'], env)
"""


class KubernetesProcessAdapter:
    def __init__(self, backend, owner, profile, generation: str, *, check_cancelled=lambda: None,
                 run_lifecycle=None):
        self.backend, self.owner, self.profile = backend, owner, profile
        self.generation = generation
        self.check_cancelled = check_cancelled
        self.run_lifecycle = run_lifecycle

    def _assert_generation(self, api):
        pod = _document(api.read_namespaced_pod(
            self.backend.resource_name(self.owner), self.owner.namespace, _request_timeout=10,
        ))
        self.backend.validate_resource(pod, self.backend.manifests(self.owner, self.profile)[0])
        if self.backend.generation(pod) != self.generation:
            raise RuntimeError('Sandbox container generation changed; command cannot resume')

    def run(self, argv: Sequence[str], *, cwd: str, env: Mapping[str, str],
            timeout_seconds: float) -> ScriptProcessResult:
        if (not argv or isinstance(argv, str) or any(not isinstance(v, str) or '\0' in v for v in argv)
                or not argv[0] or not PurePosixPath(cwd).is_absolute() or '\0' in cwd
                or not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool)
                or not math.isfinite(timeout_seconds) or timeout_seconds <= 0
                or any(not isinstance(k, str) or not k or '=' in k or '\0' in k
                       or not isinstance(v, str) or '\0' in v for k, v in env.items())):
            raise ValueError('Invalid sandbox process parameters')
        self.check_cancelled()
        payload = json.dumps({'argv': list(argv), 'cwd': cwd, 'env': dict(env)}, separators=(',', ':'))
        command = ['timeout', '--signal=TERM', '--kill-after=2', str(float(timeout_seconds)),
                   'python', '-c', _EXEC, payload]
        # Closing the exec socket does not promise process-tree termination. GNU
        # timeout bounds the remote command independently of a disconnected caller.
        deadline = time.monotonic() + timeout_seconds + 5
        with self.backend.api_factory() as api:
            self._assert_generation(api)
            holder = self.run_lifecycle.begin('process') if self.run_lifecycle is not None else None
            ws, exited = None, False
            stdout, stderr = bytearray(), bytearray()
            try:
                # The request may commit remotely even if opening its stream fails.
                ws = stream(api.connect_get_namespaced_pod_exec, self.backend.resource_name(self.owner),
                            self.owner.namespace, container='sandbox', command=command,
                            stderr=True, stdout=True, stdin=False, tty=False, binary=True,
                            _preload_content=False, _request_timeout=min(10, timeout_seconds + 5))
                while ws.is_open():
                    self.check_cancelled()
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('Sandbox exec transport deadline exceeded; effects may be incomplete')
                    ws.update(timeout=min(0.2, remaining))
                    stdout.extend(ws.read_stdout())
                    stderr.extend(ws.read_stderr())
                    if len(stdout) + len(stderr) > 16 * 1024 * 1024:
                        raise RuntimeError('Sandbox exec output exceeds the bounded control response')
                stdout.extend(ws.read_stdout())
                stderr.extend(ws.read_stderr())
                if len(stdout) + len(stderr) > 16 * 1024 * 1024:
                    raise RuntimeError('Sandbox exec output exceeds the bounded control response')
                exit_code = ws.returncode
                if type(exit_code) is not int:
                    raise RuntimeError('Sandbox exec closed without a definitive exit status')
                exited = True
                self._assert_generation(api)
                return ScriptProcessResult(bytes(stdout), bytes(stderr), exit_code)
            finally:
                try:
                    if ws is not None:
                        ws.close()
                finally:
                    if holder is not None:
                        if exited:
                            self.run_lifecycle.finish(holder)
                        else:
                            self.run_lifecycle.unknown(holder)

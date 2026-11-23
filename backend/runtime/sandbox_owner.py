# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Protected owner facts and conservative process-termination observations."""

from __future__ import annotations

import hashlib
import math
import os
import re
import time
from dataclasses import asdict
from pathlib import Path

from nexent.core.agents.sandbox_contracts import SandboxOwner

from runtime.sandbox_journal import SandboxCoordinationUnknown
from runtime.sandbox_workspace import _no_symlinks


def process_start_ticks(pid: int):
    if type(pid) is not int or pid <= 0:
        raise ValueError('Invalid Runtime PID')
    # comm may contain spaces or parentheses. The final ')' precedes state.
    text = Path(f'/proc/{pid}/stat').read_text()
    return text.rsplit(')', 1)[1].split()[19]


def process_identity(container_id, container_name):
    return {'pid': os.getpid(), 'start_ticks': process_start_ticks(os.getpid()),
            'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'container_id': container_id, 'container_name': container_name}


class SandboxOwnerFacts:
    def __init__(self, journal, owner):
        self.journal, self.owner = journal, owner
        self.directory = journal.root / 'owners' / owner.key
        _no_symlinks(self.directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        if os.name == 'posix':
            self.directory.chmod(0o700)

    @staticmethod
    def epoch_key(epoch):
        return hashlib.sha256(epoch.encode()).hexdigest()

    def path(self, epoch):
        return self.directory / (self.epoch_key(epoch) + '.json')

    @staticmethod
    def validate(fact):
        try:
            if isinstance(fact, dict):
                fact.setdefault('process_stopped_at', None)
            if (not isinstance(fact, dict) or set(fact) != {
                    'version', 'owner', 'process', 'resource_state', 'pod_name', 'pod_uid',
                    'container_id', 'profile', 'updated_at', 'process_stopped_at'} or fact['version'] != 1):
                raise ValueError('Invalid owner fact structure')
            SandboxOwner(**fact['owner'])
            if (type(fact['updated_at']) not in (int, float) or not math.isfinite(fact['updated_at'])
                    or fact['updated_at'] < 0):
                raise ValueError('Invalid owner observation timestamp')
            stopped_at = fact['process_stopped_at']
            if stopped_at is not None and (type(stopped_at) not in (int, float)
                                           or not math.isfinite(stopped_at) or stopped_at < 0):
                raise ValueError('Invalid process termination observation')
            process = fact['process']
            if (set(process) != {'pid', 'start_ticks', 'boot_id', 'container_id', 'container_name'}
                    or type(process['pid']) is not int or process['pid'] <= 0
                    or not re.fullmatch(r'[0-9]{1,32}', process['start_ticks'])
                    or any(not isinstance(process[k], str) or not process[k] or len(process[k]) > 256
                           for k in ('boot_id', 'container_id', 'container_name'))):
                raise ValueError('Invalid owner process identity')
            if fact['resource_state'] not in {'NOT_CREATED', 'CREATING', 'BOUND', 'READY', 'TERMINATED'}:
                raise ValueError('Invalid owner resource state')
            for key in ('pod_name', 'pod_uid', 'container_id', 'profile'):
                if fact[key] is not None and (not isinstance(fact[key], str) or not fact[key] or len(fact[key]) > 256):
                    raise ValueError('Invalid owner resource identity')
            state = fact['resource_state']
            if state == 'NOT_CREATED' and any(fact[key] is not None for key in (
                    'pod_name', 'pod_uid', 'container_id', 'profile')):
                raise ValueError('Unused owner has conflicting resource facts')
            if state != 'NOT_CREATED' and (fact['pod_name'] is None or fact['profile'] is None):
                raise ValueError('Resource intent identity is missing')
            if state in {'BOUND', 'READY', 'TERMINATED'} and fact['pod_uid'] is None:
                raise ValueError('Observed resource UID is missing')
            if state == 'READY' and fact['container_id'] is None:
                raise ValueError('Ready execution container identity is missing')
            return fact
        except (ValueError, TypeError, KeyError) as exc:
            raise SandboxCoordinationUnknown('Invalid protected Runtime owner facts') from exc

    def read(self, epoch):
        fact = self.journal._read(self.path(epoch))
        if fact is None:
            return None
        self.validate(fact)
        owner = SandboxOwner(**fact['owner'])
        if owner.key != self.owner.key or owner.epoch != epoch:
            raise SandboxCoordinationUnknown('Protected Runtime owner identity mismatch')
        return fact

    def initialize(self, identity):
        with self.journal.locked(self.owner.key):
            current = self.read(self.owner.epoch)
            if current is not None:
                if current['owner'] != asdict(self.owner) or current['process'] != identity:
                    raise SandboxCoordinationUnknown('Runtime owner epoch is already held by another process')
                if current['process_stopped_at'] is not None:
                    raise SandboxCoordinationUnknown('A proved stopped Runtime epoch cannot restart')
                return current
            fact = {'version': 1, 'owner': asdict(self.owner), 'process': identity,
                    'resource_state': 'NOT_CREATED', 'pod_name': None, 'pod_uid': None,
                    'container_id': None, 'profile': None, 'updated_at': time.time(), 'process_stopped_at': None}
            self.journal._write(self.path(self.owner.epoch), self.validate(fact))
            return fact

    def _current(self, owner):
        if owner != self.owner:
            raise SandboxCoordinationUnknown('Resource event belongs to another Runtime owner')
        fact = self.read(owner.epoch)
        if fact is None:
            raise SandboxCoordinationUnknown('Runtime owner facts must exist before resource mutation')
        return fact

    def creation_intent(self, owner, profile, name):
        with self.journal.locked(owner.key):
            fact = self._current(owner)
            if fact['resource_state'] == 'TERMINATED':
                raise SandboxCoordinationUnknown('Retired owner resource cannot be recreated in the same epoch')
            if fact['profile'] is not None and (fact['profile'] != profile.fingerprint or fact['pod_name'] != name):
                raise SandboxCoordinationUnknown('Runtime SYSTEM resource profile is immutable')
            if fact['resource_state'] == 'NOT_CREATED':
                fact.update(resource_state='CREATING', profile=profile.fingerprint, pod_name=name,
                            updated_at=time.time())
                self.journal._write(self.path(owner.epoch), fact)

    def observe_pod(self, owner, pod_uid, container_id=None, *, ready=False):
        with self.journal.locked(owner.key):
            fact = self._current(owner)
            if fact['resource_state'] not in {'CREATING', 'BOUND', 'READY'}:
                raise SandboxCoordinationUnknown('Sandbox resource was not declared before creation')
            if fact['pod_uid'] is not None and fact['pod_uid'] != pod_uid:
                raise SandboxCoordinationUnknown('Sandbox Pod UID changed; old execution cannot be adopted')
            if fact['container_id'] is not None and container_id is not None and fact['container_id'] != container_id:
                raise SandboxCoordinationUnknown('Sandbox container generation changed')
            fact['pod_uid'] = pod_uid
            if container_id is not None:
                fact['container_id'] = container_id
            if ready and container_id is None:
                raise ValueError('Ready resource facts require a concrete container identity')
            if ready:
                fact['resource_state'] = 'READY'
            elif fact['resource_state'] != 'READY':
                fact['resource_state'] = 'BOUND'
            fact['updated_at'] = time.time()
            self.journal._write(self.path(owner.epoch), fact)

    def terminated(self, owner, pod_uid):
        with self.journal.locked(owner.key):
            fact = self._current(owner)
            if fact['pod_uid'] != pod_uid:
                raise SandboxCoordinationUnknown('Termination evidence belongs to another Pod UID')
            fact.update(resource_state='TERMINATED', updated_at=time.time())
            self.journal._write(self.path(owner.epoch), fact)

    def missing(self, owner, kind):
        if kind != 'pod':
            return
        with self.journal.locked(owner.key):
            fact = self._current(owner)
            if fact['resource_state'] not in {'NOT_CREATED', 'TERMINATED'}:
                raise SandboxCoordinationUnknown('Missing sandbox API object does not prove execution stopped')

    def permits_pre_execution_fallback(self, owner):
        with self.journal.locked(owner.key):
            return self._current(owner)['resource_state'] == 'NOT_CREATED'

    def record_process_stopped(self):
        """Persist a verified termination so later recovery does not need to prove it again."""
        with self.journal.locked(self.owner.key):
            fact = self._current(self.owner)
            if fact['process_stopped_at'] is None:
                fact.update(process_stopped_at=time.time(), updated_at=time.time())
                self.journal._write(self.path(self.owner.epoch), fact)


class SandboxOwnerObserver:
    def __init__(self, api_factory, current_owner, current_process):
        self.api_factory, self.current_owner, self.current_process = api_factory, current_owner, current_process

    def _superseded_in_current_pod(self, owner, process, pod, statuses):
        current_owner, current = self.current_owner, self.current_process
        container_name = process['container_name']
        metadata = pod['metadata']
        spec = pod.get('spec', {})
        if (owner.key != current_owner.key or owner.pod_name != current_owner.pod_name
                or metadata.get('name') != owner.pod_name or metadata.get('namespace') != owner.namespace
                or metadata.get('deletionTimestamp') is not None
                or spec.get('hostPID', False) is not False or spec.get('shareProcessNamespace', False) is not False
                or process['pid'] != 1 or current['pid'] != 1
                or container_name != current['container_name']
                or process['container_id'] == current['container_id']):
            return False
        if sum(container.get('name') == container_name for container in spec.get('containers', ())) != 1:
            return False
        matching = [status for status in statuses if status.get('name') == container_name]
        if len(matching) != 1:
            return False
        status = matching[0]
        running = status.get('state', {}).get('running') or {}
        if status.get('containerID') != current['container_id'] or not running.get('startedAt'):
            return False
        # Kubelet starts a replacement for the same regular container after stopping
        # its predecessor. With private PID namespaces both identities are the
        # respective container init processes. The Pod UID pins the node, so a
        # different Linux boot also rules out survival of the previous process.
        return (process['boot_id'] != current['boot_id']
                or int(process['start_ticks']) < int(current['start_ticks']))

    def process_stopped(self, fact):
        """Accept exact termination or verified replacement of the local Runtime container."""
        SandboxOwnerFacts.validate(fact)
        if fact['process_stopped_at'] is not None:
            return True
        owner, process = SandboxOwner(**fact['owner']), fact['process']
        if owner.key == self.current_owner.key and process['container_id'] == self.current_process['container_id']:
            if process['boot_id'] != self.current_process['boot_id']:
                return True
            try:
                return process_start_ticks(process['pid']) != process['start_ticks']
            except FileNotFoundError:
                return True
            except (OSError, ValueError, IndexError):
                return False
        try:
            from nexent.core.agents.sandbox_kubernetes import _document

            with self.api_factory() as api:
                pod = _document(api.read_namespaced_pod(owner.pod_name, owner.namespace, _request_timeout=5))
            if pod['metadata']['uid'] != owner.pod_uid:
                return False
            statuses = pod.get('status', {}).get('containerStatuses', [])
            for status in statuses:
                if status['name'] != process['container_name']:
                    continue
                for state in (status.get('state', {}), status.get('lastState', {})):
                    terminated = state.get('terminated', {})
                    identity = terminated.get('containerID')
                    if state is status.get('state'):
                        identity = identity or status.get('containerID')
                    if identity == process['container_id'] and terminated.get('finishedAt'):
                        return True
            return self._superseded_in_current_pod(owner, process, pod, statuses)
        except Exception:
            # 404, replacement UID and API outages all preserve UNKNOWN.
            return False

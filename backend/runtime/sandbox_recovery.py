# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Recover only protected, proved stopped Runtime generations."""

from __future__ import annotations

import logging
import shutil
import time
from collections import OrderedDict
from dataclasses import replace
from pathlib import Path
from threading import Lock

from nexent.core.agents.sandbox_contracts import SandboxOwner
from nexent.core.agents.sandbox_kubernetes import _document, wait_for_sandbox_termination

from runtime.sandbox_coordination import _RELEASE
from runtime.sandbox_journal import SandboxCoordinationUnknown
from runtime.sandbox_owner import SandboxOwnerFacts
from runtime.sandbox_workspace import KubernetesWorkspace, _no_symlinks


logger = logging.getLogger(__name__)
_MISSING_POD_WARNING_INTERVAL_SECONDS = 300
_MAX_MISSING_POD_WARNINGS = 256


class _MissingSandboxPod(SandboxCoordinationUnknown):
    """The Pod API no longer has the object needed to prove execution stopped."""


class SandboxRuntimeRecovery:
    def __init__(self, coordinator, api_factory, observer, fail_work, *, workspace_root,
                 retention_seconds=86400, fail_execution=None):
        self.coordinator, self.journal = coordinator, coordinator.journal
        self.api_factory, self.observer, self.fail_work = api_factory, observer, fail_work
        self.workspace_root = Path(workspace_root).absolute()
        self.retention_seconds = retention_seconds
        self.fail_execution = fail_execution
        self._missing_pod_warnings: OrderedDict[tuple[str, str], float] = OrderedDict()
        self._missing_pod_warning_lock = Lock()

    def _warn_missing_pod(self, owner, pod_name):
        key = (owner.key, owner.epoch)
        with self._missing_pod_warning_lock:
            now = time.monotonic()
            last_warning = self._missing_pod_warnings.get(key)
            if last_warning is not None and now - last_warning < _MISSING_POD_WARNING_INTERVAL_SECONDS:
                return
            self._missing_pod_warnings[key] = now
            self._missing_pod_warnings.move_to_end(key)
            if len(self._missing_pod_warnings) > _MAX_MISSING_POD_WARNINGS:
                self._missing_pod_warnings.popitem(last=False)
        logger.warning('Sandbox Pod not found (404); recovery remains unknown '
                       'namespace=%s sandbox_pod=%s runtime_pod=%s epoch=%s',
                       owner.namespace, pod_name, owner.pod_name, owner.epoch)

    def _same_deployment(self, owner):
        current = self.coordinator.owner
        return (owner.deployment_id, owner.namespace) == (current.deployment_id, current.namespace)

    @staticmethod
    def _verify_resource(document, owner, fact):
        metadata = document.get('metadata', {})
        refs = metadata.get('ownerReferences', [])
        annotations = metadata.get('annotations', {})
        if (metadata.get('name') != fact['pod_name']
                or annotations.get('nexent.ai/epoch') != owner.epoch
                or annotations.get('nexent.ai/profile') != fact['profile']
                or len(refs) != 1 or refs[0].get('kind') != 'Pod'
                or refs[0].get('uid') != owner.pod_uid or refs[0].get('name') != owner.pod_name):
            raise SandboxCoordinationUnknown('Recovery resource ownership is conflicting')

    def _retire_resource(self, store, fact, deadline):
        if fact['resource_state'] == 'NOT_CREATED':
            return True
        owner = store.owner
        with self.api_factory() as api:
            if fact['resource_state'] == 'TERMINATED':
                self._delete_service(api, store, fact)
                return True
            try:
                pod = api.read_namespaced_pod(fact['pod_name'], owner.namespace, _request_timeout=3)
            except Exception as exc:
                if getattr(exc, 'status', None) == 404:
                    raise _MissingSandboxPod(
                        'Previous SYSTEM execution termination is unproved: sandbox Pod not found (404)',
                    ) from exc
                raise
            pod = _document(pod)
            self._verify_resource(pod, owner, fact)
            if fact['pod_uid'] is not None and pod['metadata']['uid'] != fact['pod_uid']:
                raise SandboxCoordinationUnknown('Recovery sandbox UID changed')
            # A lost create response may not have recorded the UID. Recover it
            # only from the exact immutable owner/epoch/profile resource.
            if fact['pod_uid'] is None:
                store.observe_pod(owner, pod['metadata']['uid'])
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            api.delete_namespaced_pod(fact['pod_name'], owner.namespace, body={
                'preconditions': {'uid': pod['metadata']['uid']},
                'gracePeriodSeconds': min(5, max(0, int(remaining) - 1)),
            }, _request_timeout=min(3, remaining))
            if not wait_for_sandbox_termination(api, owner.namespace, pod, deadline,
                                                container_id=fact['container_id']):
                return False
            store.terminated(owner, pod['metadata']['uid'])
            self._delete_service(api, store, fact)
        return True

    def _delete_service(self, api, store, fact):
        owner = store.owner
        try:
            service = _document(api.read_namespaced_service(fact['pod_name'], owner.namespace,
                                                             _request_timeout=3))
            epoch = service.get('metadata', {}).get('annotations', {}).get('nexent.ai/epoch')
            if isinstance(epoch, str) and 0 < len(epoch) <= 253 and epoch != owner.epoch:
                other_fact = store.read(epoch)
                if (other_fact is not None and other_fact['pod_name'] == fact['pod_name']
                        and other_fact['owner']['pod_name'] == owner.pod_name):
                    # The terminated generation's Service name can be reused in the same Runtime Pod.
                    self._verify_resource(service, replace(owner, epoch=epoch), other_fact)
                    return
            self._verify_resource(service, owner, fact)
            api.delete_namespaced_service(fact['pod_name'], owner.namespace,
                body={'preconditions': {'uid': service['metadata']['uid']}}, _request_timeout=3)
        except Exception as exc:
            if getattr(exc, 'status', None) != 404:
                raise

    def verify_current_owner_resources_absent(self, deadline):
        """A missing old journal cannot authorize adopting an old SYSTEM Pod."""
        from nexent.core.agents.sandbox_kubernetes import KubernetesSandboxBackend

        owner = self.coordinator.owner
        name = KubernetesSandboxBackend.resource_name(owner)
        with self.api_factory() as api:
            while True:
                try:
                    pod = _document(api.read_namespaced_pod(name, owner.namespace, _request_timeout=3))
                except Exception as exc:
                    if getattr(exc, 'status', None) == 404:
                        break
                    raise
                if not pod.get('metadata', {}).get('deletionTimestamp'):
                    raise SandboxCoordinationUnknown('Previous SYSTEM Pod has not been safely reconciled')
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise SandboxCoordinationUnknown('Previous SYSTEM Pod deletion is not complete')
                time.sleep(min(0.1, remaining))
            try:
                api.read_namespaced_service(name, owner.namespace, _request_timeout=3)
            except Exception as exc:
                if getattr(exc, 'status', None) == 404:
                    return
                raise
            raise SandboxCoordinationUnknown('Previous SYSTEM Service has not been safely reconciled')

    def _owner_stopped(self, owner, fact, store, deadline, *, startup):
        current = self.coordinator.owner
        if owner == current:
            return False
        stopped = self.observer.process_stopped(fact)
        same_pod = owner.key == current.key
        if not stopped:
            if startup and same_pod:
                raise SandboxCoordinationUnknown('Previous process in this Runtime Pod is still live or unknown')
            return False
        store.record_process_stopped()
        retired = self._retire_resource(store, fact, deadline)
        if startup and same_pod and not retired:
            raise SandboxCoordinationUnknown('Previous SYSTEM execution termination is unproved')
        return retired

    def _cleanup_workspace(self, record):
        if record.workspace_path is None:
            return False
        owner = SandboxOwner(**record.owner)
        expected = KubernetesWorkspace(self.workspace_root, owner, execution_gid=1000).run_path(
            record.tenant_id, record.user_id, record.run_id,
        )
        actual = Path(record.workspace_path).absolute()
        if actual != expected:
            raise SandboxCoordinationUnknown('Recovery workspace does not match its protected business identity')
        _no_symlinks(actual)
        if not actual.exists():
            return False
        if not actual.is_dir():
            raise SandboxCoordinationUnknown('Recovery workspace is not a directory')
        # Its ancestors are root owned and not writable by the execution UID.
        # rmtree does not follow symlinks inside the exact run directory.
        shutil.rmtree(actual)
        return True

    def _recover_run(self, record):
        with self.journal.locked(record.business_key):
            record = self.journal.read_run(record.run_id)
            if record is None or record.phase == 'TERMINAL':
                return False
            owner = SandboxOwner(**record.owner)
            if self.fail_work is not None:
                associations = {key: value for key, value in record.associations.items() if key != 'user_message_id'}
                self.fail_work(tenant_id=record.tenant_id, user_id=record.user_id,
                               conversation_id=record.conversation_id, **associations,
                               evaluation_batch=(record.kind == 'EVALUATION'
                                   and record.associations['evaluation_id'] is not None
                                   and record.associations['evaluation_case_id'] is None))
            if self.fail_execution is not None and type(record.conversation_id) is int and record.conversation_id > 0:
                self.fail_execution(record.tenant_id, record.user_id, record.conversation_id, record.run_id)
            # Compare every ownership field; a newer pointer/lease is untouched.
            self.coordinator.client.eval(_RELEASE, 1, self.coordinator.redis_key(record.business_key),
                record.run_id, owner.pod_uid, owner.epoch, record.token_hash, self.coordinator.lease_seconds)
            self.coordinator.client.eval("""
                if redis.call('HGET', KEYS[1], 'generation') ~= ARGV[1] then return 0 end
                redis.call('HSET', KEYS[1], 'status', 'failed')
                redis.call('HSET', KEYS[2], 'status', 'failed', 'error', 'Runtime execution was interrupted.')
                for _, key in ipairs(KEYS) do redis.call('EXPIRE', key, ARGV[2]) end
                return 1
            """, 2, 'runtime:ksm:state:' + record.business_key + ':' + record.run_id,
                'runtime:ksm:state:' + record.business_key + ':' + record.run_id + ':done',
                record.run_id, self.retention_seconds)
            record.phase, record.updated_at = 'TERMINAL', time.time()
            self.journal.write_run(record)
            return True

    def _collect_terminal(self, record):
        with self.journal.locked(record.business_key):
            current_record = self.journal.read_run(record.run_id)
            if current_record is None or current_record.phase != 'TERMINAL':
                return
            self._cleanup_workspace(current_record)
            if time.time() - current_record.updated_at < self.retention_seconds:
                return
            current = self.journal.read_current(record.business_key)
            if current is not None and current.run_id == record.run_id:
                (self.journal.root / 'current' / (record.business_key + '.json')).unlink()
            (self.journal.root / 'runs' / (record.run_id + '.json')).unlink()

    def recover(self, *, startup=False, deadline=None):
        deadline = time.monotonic() + 15 if deadline is None else deadline
        result = {'recovered_runs': 0, 'unknown_owners': 0, 'restart_confirmed': False}
        stopped = set()
        retired_facts = []
        peer_unresolved = False
        # Reconcile previous epochs even if no run reached journal publication.
        for directory in (self.journal.root / 'owners').glob('*'):
            if startup and directory.name != self.coordinator.owner.key:
                # A scale-out must not synchronously probe every live replica.
                # Their exact run markers still block duplicate conversations.
                continue
            _no_symlinks(directory)
            for path in directory.glob('*.json'):
                if time.monotonic() >= deadline:
                    if startup:
                        raise SandboxCoordinationUnknown('Owner reconciliation startup deadline exceeded')
                    return result
                owner = None
                try:
                    _no_symlinks(path)
                    fact = SandboxOwnerFacts.validate(self.journal._read(path))
                    owner = SandboxOwner(**fact['owner'])
                    if not self._same_deployment(owner):
                        continue
                    store = SandboxOwnerFacts(self.journal, owner)
                    if path != store.path(owner.epoch):
                        raise SandboxCoordinationUnknown('Owner fact path does not match its identity')
                    if self._owner_stopped(owner, fact, store, deadline, startup=startup):
                        stopped.add((owner.key, owner.epoch))
                        retired_facts.append(store)
                    elif owner != self.coordinator.owner:
                        peer_unresolved = True
                except Exception as exc:
                    result['unknown_owners'] += 1
                    if startup and (owner is None or owner.key == self.coordinator.owner.key):
                        raise
                    if isinstance(exc, _MissingSandboxPod):
                        self._warn_missing_pod(owner, fact['pod_name'])
                    else:
                        logger.warning('Sandbox owner recovery preserved unknown state', exc_info=True)
        for path in (self.journal.root / 'runs').glob('*.json'):
            if time.monotonic() >= deadline:
                break
            try:
                record = self.journal.read_run(path.stem)
                owner = SandboxOwner(**record.owner)
                if not self._same_deployment(owner):
                    continue
                if record.phase == 'TERMINAL':
                    self._collect_terminal(record)
                elif (owner.key, owner.epoch) in stopped:
                    result['recovered_runs'] += int(self._recover_run(record))
            except Exception:
                result['unknown_owners'] += 1
                logger.warning('Sandbox run recovery preserved unknown state run_id=%s', path.stem, exc_info=True)
        if not startup:
            # A scale-out or an incomplete owner observation cannot establish a restart.
            result['restart_confirmed'] = bool(stopped) and not (peer_unresolved or result['unknown_owners'])
            self._collect_owner_facts(retired_facts, deadline)
        return result

    def _collect_owner_facts(self, stores, deadline):
        remaining_owners = set()
        try:
            for path in (self.journal.root / 'runs').glob('*.json'):
                if time.monotonic() >= deadline:
                    return
                record = self.journal.read_run(path.stem)
                owner = SandboxOwner(**record.owner)
                remaining_owners.add((owner.key, owner.epoch))
        except Exception:
            # A corrupt association cannot authorize deleting owner evidence.
            return
        for store in stores:
            owner = store.owner
            if time.monotonic() >= deadline or (owner.key, owner.epoch) in remaining_owners:
                continue
            with self.journal.locked(owner.key):
                fact = store.read(owner.epoch)
                if (fact is not None and fact['process_stopped_at'] is not None
                        and fact['resource_state'] in {'NOT_CREATED', 'TERMINATED'}
                        and time.time() - fact['updated_at'] >= self.retention_seconds):
                    store.path(owner.epoch).unlink()

    def recovery_loop(self, cancel_event):
        while not cancel_event.wait(5):
            try:
                self.recover()
            except Exception:
                logger.warning('Sandbox scoped recovery is unavailable', exc_info=True)

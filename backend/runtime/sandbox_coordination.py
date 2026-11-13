# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Redis compare-token leases guarded by protected RWX current-run facts."""

from __future__ import annotations

import logging
import secrets
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from runtime.sandbox_journal import SandboxCoordinationUnknown, SandboxRunJournal, SandboxRunRecord


logger = logging.getLogger(__name__)


_CLAIM = """
if #KEYS > 1 and redis.call('HGET', KEYS[2], 'token_hash') ~= ARGV[7] then return -1 end
if redis.call('EXISTS', KEYS[1]) == 1 then return 0 end
redis.call('HSET', KEYS[1], 'run_id', ARGV[1], 'owner_uid', ARGV[2],
           'owner_epoch', ARGV[3], 'token_hash', ARGV[4], 'phase', ARGV[6] or 'INTENT')
redis.call('EXPIRE', KEYS[1], ARGV[5])
return 1
"""
_COMPARE = """
if redis.call('HGET', KEYS[1], 'run_id') ~= ARGV[1]
or redis.call('HGET', KEYS[1], 'owner_uid') ~= ARGV[2]
or redis.call('HGET', KEYS[1], 'owner_epoch') ~= ARGV[3]
or redis.call('HGET', KEYS[1], 'token_hash') ~= ARGV[4] then return 0 end
"""
_RENEW = _COMPARE + """
redis.call('EXPIRE', KEYS[1], ARGV[5])
if #KEYS > 1 then
    if redis.call('HGET', KEYS[3], 'generation') == ARGV[1] then
        redis.call('EXPIRE', KEYS[3], ARGV[6])
        if redis.call('HGET', KEYS[2], 'generation') == ARGV[1] then
            redis.call('EXPIRE', KEYS[2], ARGV[6])
        end
        redis.call('EXPIRE', KEYS[4], ARGV[7])
        redis.call('EXPIRE', KEYS[5], ARGV[8])
        redis.call('EXPIRE', KEYS[6], ARGV[9])
    end
end
return 1
"""
_RELEASE = _COMPARE + "return redis.call('DEL', KEYS[1])"
_ACTIVATE = _COMPARE + """
if #KEYS > 1 and redis.call('HGET', KEYS[2], 'token_hash') ~= ARGV[6] then return -1 end
redis.call('HSET', KEYS[1], 'phase', 'ACTIVE')
redis.call('EXPIRE', KEYS[1], ARGV[5])
return 1
"""


class SandboxRunBusy(RuntimeError):
    """An active or unknown run prevents duplicate business admission."""


@dataclass(frozen=True)
class SandboxRunLease:
    run_id: str
    business_key: str
    token: str


@dataclass(frozen=True)
class SandboxRunReference:
    run_id: str
    business_key: str
    tenant_id: str
    user_id: str
    conversation_id: int | str
    owner_uid: str
    owner_epoch: str
    token_hash: str
    phase: str
    automation_generation: str = ''
    assistant_message_id: int | str | None = None


class SandboxRunLifecycle:
    """Keep one admitted run until its actual descendants and callbacks finish."""

    def __init__(self, coordinator, lease):
        self.coordinator, self.lease = coordinator, lease

    def begin(self, kind):
        if kind not in {'kernel', 'invocation', 'callback', 'process'}:
            raise ValueError('Unknown run lifetime holder')
        holder = kind + ':' + uuid.uuid4().hex
        self.coordinator.hold(self.lease, holder)
        return holder

    def finish(self, holder):
        try:
            return self.coordinator.finish(self.lease, holder=holder)
        except Exception:
            self.coordinator.signal_lost()
            raise

    def unknown(self, holder):
        coordinator = self.coordinator
        try:
            with coordinator.journal.locked(self.lease.business_key):
                record = coordinator._current(self.lease)
                record.phase, record.updated_at = 'UNKNOWN', time.time()
                coordinator.journal.write_run(record)
        except Exception:
            coordinator.signal_lost()
            raise


class SandboxRunCoordinator:
    def __init__(self, client, journal: SandboxRunJournal, owner, *, lease_seconds=60, workspace_root=None):
        if type(lease_seconds) is not int or lease_seconds < 3:
            raise ValueError('Sandbox coordination lease must be at least three seconds')
        self.client, self.journal, self.owner, self.lease_seconds = client, journal, owner, lease_seconds
        self.workspace_root = workspace_root
        self._lock = threading.Lock()
        self._active: dict[str, tuple[SandboxRunLease, object]] = {}
        self._holds: dict[str, set[str]] = {}
        self.lost_coordination = threading.Event()
        self.owner_facts = None
        self._state_ttls = None
        self._owner_lease = None
        self._loss_cancellation_sent = False
        self._admission_closed = threading.Event()

    @property
    def active_count(self):
        with self._lock:
            return len(self._active)

    def owner_redis_key(self):
        return 'runtime:ksm:owner:' + self.owner.key + ':' + self.journal.token_hash(self.owner.epoch)

    def claim_owner(self):
        if self._owner_lease is None:
            self._owner_lease = SandboxRunLease(self.owner.epoch, self.owner.key, secrets.token_hex(32))
        try:
            claimed = self.client.eval(_CLAIM, 1, self.owner_redis_key(), *self._args(self._owner_lease), 'ACTIVE')
            if claimed != 1:
                claimed = self.client.eval(_RENEW, 1, self.owner_redis_key(), *self._args(self._owner_lease))
            if claimed != 1:
                raise SandboxCoordinationUnknown('Runtime owner heartbeat identity is conflicting')
        except Exception as exc:
            self.signal_lost()
            raise SandboxCoordinationUnknown('Runtime owner heartbeat could not be established') from exc

    def configure_state_ttls(self, run_ttl, stream_ttl, completed_ttl, cancel_ttl):
        policy = (run_ttl, stream_ttl, completed_ttl, cancel_ttl)
        if self._state_ttls is not None and self._state_ttls != policy:
            raise ValueError('Runtime state renewal policy is immutable')
        self._state_ttls = policy

    @staticmethod
    def _state_keys(lease):
        prefix = 'runtime:ksm:state:' + lease.business_key
        run = prefix + ':' + lease.run_id
        return (prefix + ':current', run, run + ':stream', run + ':done', run + ':cancel')

    def redis_key(self, business_key):
        return 'runtime:ksm:lease:' + business_key

    def _args(self, lease):
        return (lease.run_id, self.owner.pod_uid, self.owner.epoch,
                self.journal.token_hash(lease.token), self.lease_seconds)

    def _current(self, lease):
        record = self.journal.read_current(lease.business_key)
        if (record is None or record.run_id != lease.run_id or record.owner != asdict(self.owner)
                or record.token_hash != self.journal.token_hash(lease.token) or record.phase == 'TERMINAL'):
            raise SandboxCoordinationUnknown('Sandbox run lease is no longer the current owner')
        return record

    @staticmethod
    def _reference(record):
        return SandboxRunReference(
            record.run_id, record.business_key, record.tenant_id, record.user_id, record.conversation_id,
            record.owner['pod_uid'], record.owner['epoch'], record.token_hash, record.phase,
            str(record.associations['automation_run_id'] or ''),
            record.associations['assistant_message_id'],
        )

    def reference(self, lease):
        with self.journal.locked(lease.business_key):
            return self._reference(self._current(lease))

    def current_reference(self, tenant_id, user_id, conversation_id):
        key = self.journal.business_key(
            self.owner.deployment_id, self.owner.namespace, tenant_id, user_id, conversation_id,
        )
        with self.journal.locked(key):
            record = self.journal.read_current(key)
            return self._reference(record) if record is not None else None

    def bind_cancellation(self, lease, cancel):
        with self._lock:
            existing = self._active.get(lease.run_id)
            if existing is None or existing[0] != lease:
                raise SandboxCoordinationUnknown('Sandbox run is not locally owned')
            previous = existing[1]

            def cancel_both():
                try:
                    previous()
                finally:
                    cancel()

            self._active[lease.run_id] = (lease, cancel_both)

    def signal_lost(self):
        with self._lock:
            self.lost_coordination.set()
            send = not self._loss_cancellation_sent
            self._loss_cancellation_sent = True
        if send:
            self.cancel_active()

    def cancel_active(self):
        self._admission_closed.set()
        with self._lock:
            callbacks = [cancel for _, cancel in self._active.values()]
        for cancel in callbacks:
            try:
                cancel()
            except Exception:
                logger.warning('Sandbox cancellation failed for an owned run')

    def reserve(self, tenant_id, user_id, conversation_id, run_id, *, kind='CHAT', cancel=lambda: None):
        if self.lost_coordination.is_set() or self._admission_closed.is_set():
            raise SandboxCoordinationUnknown('Runtime has lost sandbox coordination; new execution is closed')
        key = self.journal.business_key(
            self.owner.deployment_id, self.owner.namespace, tenant_id, user_id, conversation_id,
        )
        lease = SandboxRunLease(run_id, key, secrets.token_hex(32))
        record = SandboxRunRecord(run_id, key, asdict(self.owner), tenant_id, user_id, conversation_id,
                                  self.journal.token_hash(lease.token), kind=kind).validate()
        with self.journal.locked(key):
            if self.lost_coordination.is_set() or self._admission_closed.is_set():
                raise SandboxCoordinationUnknown('Runtime lost coordination before admission')
            current = self.journal.read_current(key)
            if current is not None and current.phase != 'TERMINAL':
                # Expired/missing Redis keys cannot override this durable fact.
                raise SandboxRunBusy('The conversation has an active or unknown owner')
            try:
                keys, args = (self.redis_key(key),), self._args(lease)
                if self._owner_lease is not None:
                    keys += (self.owner_redis_key(),)
                    args += ('INTENT', self.journal.token_hash(self._owner_lease.token))
                claimed = self.client.eval(_CLAIM, len(keys), *keys, *args)
            except Exception as exc:
                self.lost_coordination.set()
                raise SandboxCoordinationUnknown('Redis admission could not be confirmed') from exc
            if claimed == -1:
                self.signal_lost()
                raise SandboxCoordinationUnknown('Runtime owner heartbeat was lost before admission')
            if claimed != 1:
                raise SandboxRunBusy('The conversation Redis reservation is still held')
            try:
                self.journal.publish(record)
            except BaseException:
                # A partially published INTENT remains conservative. No business
                # action may run until reserve returns and activate rechecks it.
                try:
                    self.client.eval(_RELEASE, 1, self.redis_key(key), *self._args(lease))
                except Exception:
                    self.lost_coordination.set()
                raise
        with self._lock:
            self._active[lease.run_id] = (lease, cancel)
            self._holds[lease.run_id] = {'execution'}
            lost = self.lost_coordination.is_set()
        lost = lost or self._admission_closed.is_set()
        if lost:
            try:
                self.finish(lease)
            finally:
                cancel()
            raise SandboxCoordinationUnknown('Runtime lost coordination during admission')
        return lease

    def hold(self, lease, holder):
        with self._lock:
            if self._active.get(lease.run_id, (None,))[0] != lease or not self._holds.get(lease.run_id):
                raise SandboxCoordinationUnknown('Cannot add a holder to a closing Runtime run')
            self._holds[lease.run_id].add(holder)

    def lifecycle(self, run_id):
        with self._lock:
            active = self._active.get(run_id)
            if active is None:
                raise SandboxCoordinationUnknown('Run lifetime has no locally admitted execution')
            return SandboxRunLifecycle(self, active[0])

    def associate(self, lease, **associations):
        with self.journal.locked(lease.business_key):
            record = self._current(lease)
            for key, value in associations.items():
                if key not in record.associations or value is None:
                    raise ValueError('Unknown or empty sandbox business association')
                previous = record.associations[key]
                if previous is not None and previous != value:
                    raise SandboxCoordinationUnknown('Sandbox business association is immutable')
                record.associations[key] = value
            record.updated_at = time.time()
            self.journal.write_run(record)

    def record_workspace(self, run_id, path):
        from runtime.sandbox_workspace import KubernetesWorkspace, _no_symlinks

        with self._lock:
            active = self._active.get(run_id)
        if active is None or self.workspace_root is None:
            raise SandboxCoordinationUnknown('Workspace has no admitted Runtime run')
        lease = active[0]
        with self.journal.locked(lease.business_key):
            record = self._current(lease)
            expected = KubernetesWorkspace(self.workspace_root, self.owner, execution_gid=1000).run_path(
                record.tenant_id, record.user_id, record.run_id,
            )
            actual = Path(path).absolute()
            _no_symlinks(actual)
            if actual != expected:
                raise SandboxCoordinationUnknown('Workspace does not match its admitted owner and business identity')
            record.workspace_path = str(actual)
            self.journal.write_run(record)

    def activate(self, lease):
        with self.journal.locked(lease.business_key):
            record = self._current(lease)
            if record.phase == 'UNKNOWN' or self.lost_coordination.is_set():
                raise SandboxCoordinationUnknown('Sandbox run coordination is unknown')
            try:
                keys, args = (self.redis_key(lease.business_key),), self._args(lease)
                if self._owner_lease is not None:
                    keys += (self.owner_redis_key(),)
                    args += (self.journal.token_hash(self._owner_lease.token),)
                confirmed = self.client.eval(_ACTIVATE, len(keys), *keys, *args)
            except Exception as exc:
                self._mark_unknown_locked(record)
                raise SandboxCoordinationUnknown('Redis execution ownership could not be confirmed') from exc
            if confirmed != 1:
                if confirmed == -1:
                    self.signal_lost()
                self._mark_unknown_locked(record)
                raise SandboxCoordinationUnknown('Sandbox execution lease was lost')
            record.phase, record.updated_at = 'ACTIVE', time.time()
            self.journal.write_run(record)

    def _mark_unknown_locked(self, record):
        self.lost_coordination.set()
        record.phase, record.updated_at = 'UNKNOWN', time.time()
        self.journal.write_run(record)

    def renew_active(self):
        with self._lock:
            active = list(self._active.values())
        if not active and self._owner_lease is None:
            return
        cancel_already_sent = False
        try:
            pipeline = self.client.pipeline(transaction=False)
            if self._owner_lease is not None:
                pipeline.eval(_RENEW, 1, self.owner_redis_key(), *self._args(self._owner_lease))
            for lease, _ in active:
                keys = (self.redis_key(lease.business_key),)
                args = self._args(lease)
                if self._state_ttls is not None:
                    keys += self._state_keys(lease)
                    args += self._state_ttls
                pipeline.eval(_RENEW, len(keys), *keys, *args)
            results = pipeline.execute()
            if len(results) != len(active) + (1 if self._owner_lease is not None else 0):
                raise SandboxCoordinationUnknown('Incomplete Redis lease renewal response')
            if self._owner_lease is not None and results.pop(0) != 1:
                self.signal_lost()
                cancel_already_sent = True
                results = [0] * len(active)
        except Exception:
            self.signal_lost()
            cancel_already_sent = True
            results = [0] * len(active)
        for (lease, cancel), renewed in zip(active, results):
            if renewed == 1:
                continue
            with self._lock:
                if self._active.get(lease.run_id, (None,))[0] != lease:
                    continue
            cancel_required = True
            try:
                with self.journal.locked(lease.business_key):
                    previous = self.journal.read_run(lease.run_id)
                    if (previous is not None and previous.phase == 'TERMINAL'
                            and previous.owner == asdict(self.owner)
                            and previous.token_hash == self.journal.token_hash(lease.token)):
                        cancel_required = False
                    else:
                        self._mark_unknown_locked(self._current(lease))
            except Exception:
                self.lost_coordination.set()
                logger.warning('Sandbox renewal ownership could not be reconciled run_id=%s', lease.run_id)
            finally:
                # Cancellation is always attempted even if the CSI view failed.
                if cancel_required and not cancel_already_sent:
                    try:
                        cancel()
                    except Exception:
                        logger.warning('Sandbox lost-coordination cancellation failed run_id=%s', lease.run_id)

    def finish(self, lease, *, holder='execution'):
        """Caller must prove its worker Future and business finalization are done."""
        with self._lock:
            holds = self._holds.get(lease.run_id)
            if holds is not None:
                if self._active[lease.run_id][0] != lease:
                    raise SandboxCoordinationUnknown('Runtime completion token is stale')
                holds.discard(holder)
                if holds:
                    return False
        with self.journal.locked(lease.business_key):
            current = self.journal.read_current(lease.business_key)
            if current is not None and current.run_id == lease.run_id and current.phase == 'TERMINAL':
                return False
            record = self._current(lease)
            try:
                self.client.eval(_RELEASE, 1, self.redis_key(lease.business_key), *self._args(lease))
                if self._state_ttls is not None:
                    index, run, stream, done, cancel = self._state_keys(lease)
                    self.client.eval("""
                        if redis.call('HGET', KEYS[2], 'generation') ~= ARGV[1] then return 0 end
                        if redis.call('HGET', KEYS[1], 'generation') == ARGV[1] then
                            redis.call('EXPIRE', KEYS[1], ARGV[2])
                        end
                        for i = 2, #KEYS do redis.call('EXPIRE', KEYS[i], ARGV[2]) end
                        return 1
                    """, 5, index, run, stream, done, cancel, lease.run_id, self._state_ttls[2])
            except Exception:
                self.lost_coordination.set()
            # Under the current-pointer lock, a proved completed local worker is
            # authoritative even after Redis loss; it never permits live takeover.
            record.phase, record.updated_at = 'TERMINAL', time.time()
            self.journal.write_run(record)
        with self._lock:
            self._active.pop(lease.run_id, None)
            self._holds.pop(lease.run_id, None)
        return True

    def renewal_loop(self, cancel_event):
        interval = min(5, self.lease_seconds / 3)
        if self._state_ttls is not None:
            interval = min(interval, min(self._state_ttls) / 3)
        while not cancel_event.wait(interval):
            self.renew_active()

# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Small protected RWX run associations; this is not sandbox business storage."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath

from nexent.core.agents.sandbox_contracts import SandboxOwner

from runtime.sandbox_workspace import _no_symlinks


class SandboxCoordinationUnknown(RuntimeError):
    """Ownership cannot be proved; accepting or recovering work is unsafe."""


_IDS = {'user_message_id', 'assistant_message_id', 'evaluation_id', 'evaluation_case_id',
        'automation_run_id', 'automation_task_id', 'automation_lock_owner'}
_PHASES = {'INTENT', 'ACTIVE', 'UNKNOWN', 'TERMINAL'}


@dataclass
class SandboxRunRecord:
    run_id: str
    business_key: str
    owner: dict
    tenant_id: str
    user_id: str
    conversation_id: int | str
    token_hash: str
    kind: str = 'CHAT'
    phase: str = 'INTENT'
    associations: dict = field(default_factory=lambda: dict.fromkeys(sorted(_IDS)))
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    version: int = 1
    workspace_path: str | None = None

    def validate(self):
        if self.version != 1 or self.phase not in _PHASES or self.kind not in {
                'CHAT', 'DEBUG', 'WORKBENCH', 'AUTOMATION', 'EVALUATION'}:
            raise SandboxCoordinationUnknown('Invalid sandbox journal version or state')
        for value, size in ((self.run_id, 32), (self.business_key, 64), (self.token_hash, 64)):
            if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{' + str(size) + '}', value):
                raise SandboxCoordinationUnknown('Invalid sandbox journal identity')
        try:
            SandboxOwner(**self.owner)
        except (ValueError, TypeError) as exc:
            raise SandboxCoordinationUnknown('Invalid sandbox journal owner') from exc
        if (any(not isinstance(v, str) or not v or len(v) > 4096 for v in (self.tenant_id, self.user_id))
                or type(self.conversation_id) not in (int, str) or len(str(self.conversation_id)) > 256
                or set(self.associations) != _IDS):
            raise SandboxCoordinationUnknown('Invalid sandbox journal business associations')
        for value in self.associations.values():
            if value is not None and (type(value) not in (int, str) or len(str(value)) > 256):
                raise SandboxCoordinationUnknown('Invalid sandbox journal association value')
        expected = SandboxRunJournal.business_key(
            self.owner['deployment_id'], self.owner['namespace'], self.tenant_id, self.user_id, self.conversation_id,
        )
        if expected != self.business_key:
            raise SandboxCoordinationUnknown('Sandbox journal business identity mismatch')
        if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0
               for v in (self.created_at, self.updated_at)):
            raise SandboxCoordinationUnknown('Invalid sandbox journal timestamp')
        if self.workspace_path is not None:
            value = self.workspace_path
            if (not isinstance(value, str) or len(value) > 4096
                    or not (PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute())
                    or '..' in PurePosixPath(value).parts or '..' in PureWindowsPath(value).parts):
                raise SandboxCoordinationUnknown('Invalid sandbox journal workspace')
        return self


class SandboxRunJournal:
    def __init__(self, root: str | Path, *, lock_timeout_seconds: float = 5):
        self.root = Path(root).absolute()
        self.lock_timeout_seconds = lock_timeout_seconds
        if not math.isfinite(lock_timeout_seconds) or lock_timeout_seconds <= 0:
            raise ValueError('Sandbox journal lock timeout must be positive and finite')
        _no_symlinks(self.root)
        for directory in (self.root, self.root / 'runs', self.root / 'current', self.root / 'locks'):
            directory.mkdir(parents=True, exist_ok=True)
            _no_symlinks(directory)
            if os.name == 'posix':
                info = directory.stat()
                if info.st_uid != os.geteuid():
                    raise SandboxCoordinationUnknown('Sandbox journal must be owned by the trusted Runtime')
                directory.chmod(0o700)

    @staticmethod
    def business_key(deployment_id, namespace, tenant_id, user_id, conversation_id):
        if isinstance(conversation_id, str) and re.fullmatch(r'evaluation:[1-9][0-9]*', conversation_id):
            # This reserved internal parent key fences all actors retrying the
            # same evaluation. Public conversations are integers; child cases
            # and debug runs keep their ordinary user-scoped identities.
            identity = ['evaluation-parent', deployment_id, namespace, tenant_id, conversation_id]
        else:
            identity = [deployment_id, namespace, tenant_id, user_id, str(conversation_id)]
        data = json.dumps(identity, separators=(',', ':'))
        return hashlib.sha256(data.encode()).hexdigest()

    @staticmethod
    def token_hash(token):
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def _key(value, size):
        if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{' + str(size) + '}', value):
            raise SandboxCoordinationUnknown('Invalid sandbox journal path identity')
        return value

    def _read(self, path):
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise SandboxCoordinationUnknown('Sandbox journal cannot be read safely') from exc
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 65536
                    or (os.name == 'posix' and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600))):
                raise SandboxCoordinationUnknown('Unsafe sandbox journal file')
            try:
                return json.loads(stream.read(65537))
            except (ValueError, UnicodeError) as exc:
                raise SandboxCoordinationUnknown('Corrupt sandbox journal file') from exc

    def _write(self, path, value):
        payload = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
        if len(payload) > 65536:
            raise SandboxCoordinationUnknown('Sandbox journal record exceeds limit')
        temporary = path.with_name('.' + uuid.uuid4().hex + '.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            if os.name == 'posix':
                directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)

    @contextmanager
    def locked(self, business_key):
        """Cross-process RWX locking is a required CSI preflight, not assumed."""
        key = self._key(business_key, 64)
        path = self.root / 'locks' / (key + '.lock')
        fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        deadline = time.monotonic() + self.lock_timeout_seconds
        acquired = False
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise SandboxCoordinationUnknown('Invalid sandbox coordination lock')
            if os.fstat(fd).st_size == 0:
                os.write(fd, b'0')
            while not acquired:
                try:
                    if os.name == 'posix':
                        import fcntl

                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    else:
                        import msvcrt

                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    acquired = True
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise SandboxCoordinationUnknown('Sandbox coordination lock unavailable') from exc
                    time.sleep(0.02)
            yield
        finally:
            try:
                if acquired:
                    if os.name == 'posix':
                        fcntl.flock(fd, fcntl.LOCK_UN)
                    else:
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            finally:
                os.close(fd)

    def read_run(self, run_id):
        value = self._read(self.root / 'runs' / (self._key(run_id, 32) + '.json'))
        if value is None:
            return None
        try:
            record = SandboxRunRecord(**value).validate()
            if record.run_id != run_id:
                raise SandboxCoordinationUnknown('Sandbox journal run identity mismatch')
            return record
        except (TypeError, AttributeError) as exc:
            raise SandboxCoordinationUnknown('Invalid sandbox journal record') from exc

    def read_current(self, business_key):
        value = self._read(self.root / 'current' / (self._key(business_key, 64) + '.json'))
        if value is None:
            return None
        if (not isinstance(value, dict) or set(value) != {'version', 'run_id', 'business_key'}
                or value['version'] != 1 or value['business_key'] != business_key):
            raise SandboxCoordinationUnknown('Invalid sandbox journal current pointer')
        record = self.read_run(value['run_id'])
        if record is None or record.business_key != business_key:
            raise SandboxCoordinationUnknown('Sandbox journal current association is missing')
        return record

    def write_run(self, record):
        record.validate()
        previous = self.read_run(record.run_id)
        if previous is not None:
            if (previous.business_key != record.business_key or previous.owner != record.owner
                    or previous.token_hash != record.token_hash
                    or (previous.workspace_path is not None and previous.workspace_path != record.workspace_path)
                    or (previous.phase == 'TERMINAL' and record.phase != 'TERMINAL')
                    or any(value is not None and record.associations[key] != value
                           for key, value in previous.associations.items())):
                raise SandboxCoordinationUnknown('Sandbox journal identity or association is immutable')
        self._write(self.root / 'runs' / (record.run_id + '.json'), asdict(record))

    def publish(self, record):
        self.write_run(record)
        self._write(self.root / 'current' / (record.business_key + '.json'), {
            'version': 1, 'run_id': record.run_id, 'business_key': record.business_key,
        })

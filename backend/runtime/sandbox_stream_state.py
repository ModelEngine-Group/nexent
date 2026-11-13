# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Generation-bound Redis streams for the Kubernetes Runtime protocol."""

import time

from runtime.sandbox_coordination import SandboxRunReference
from runtime.sandbox_journal import SandboxCoordinationUnknown


_CURRENT = "if redis.call('HGET', KEYS[1], 'generation') ~= ARGV[1] then return 0 end\n"
_LEASE = """
if redis.call('HGET', KEYS[2], 'run_id') ~= ARGV[1]
or redis.call('HGET', KEYS[2], 'token_hash') ~= ARGV[2]
or redis.call('HGET', KEYS[2], 'owner_uid') ~= ARGV[3]
or redis.call('HGET', KEYS[2], 'owner_epoch') ~= ARGV[4] then return 0 end
"""


class SandboxStreamState:
    def __init__(self, coordinator, *, run_ttl, completed_ttl, stream_ttl, cancel_ttl, max_stream_length):
        limits = (run_ttl, completed_ttl, stream_ttl, cancel_ttl, max_stream_length)
        if any(type(value) is not int or value <= 0 for value in limits):
            raise ValueError('Runtime stream limits must be positive integers')
        self.coordinator, self.client = coordinator, coordinator.client
        self.run_ttl, self.completed_ttl, self.stream_ttl = run_ttl, completed_ttl, stream_ttl
        self.cancel_ttl, self.max_stream_length = cancel_ttl, max_stream_length
        coordinator.configure_state_ttls(run_ttl, stream_ttl, completed_ttl, cancel_ttl)

    @staticmethod
    def _ref(user_id, conversation_id, reference):
        if (not isinstance(reference, SandboxRunReference) or reference.user_id != user_id
                or str(reference.conversation_id) != str(conversation_id)):
            raise SandboxCoordinationUnknown('Runtime state requires its immutable admitted run reference')
        return reference

    @staticmethod
    def _prefix(reference):
        return 'runtime:ksm:state:' + reference.business_key

    def keys(self, reference):
        prefix = self._prefix(reference)
        run = prefix + ':' + reference.run_id
        return prefix + ':current', run, run + ':stream', run + ':done', run + ':cancel'

    def _call(self, method, *args, **kwargs):
        try:
            return getattr(self.client, method)(*args, **kwargs)
        except Exception as exc:
            self.coordinator.signal_lost()
            raise SandboxCoordinationUnknown('Runtime Redis state is unavailable') from exc

    def reset_stream(self, user_id, conversation_id, generation=None, *, run_ref=None):
        ref = self._ref(user_id, conversation_id, run_ref)
        index, run, stream, done, cancel = self.keys(ref)
        result = self._call('eval', _LEASE + """
            if redis.call('HGET', KEYS[3], 'generation') == ARGV[1] then return 1 end
            redis.call('HSET', KEYS[1], 'generation', ARGV[1], 'automation_generation', ARGV[5])
            redis.call('EXPIRE', KEYS[1], ARGV[6])
            redis.call('HSET', KEYS[3], 'generation', ARGV[1], 'status', 'preparing',
                       'owner_uid', ARGV[3], 'owner_epoch', ARGV[4], 'updated_at', ARGV[7])
            redis.call('EXPIRE', KEYS[3], ARGV[6])
            redis.call('DEL', KEYS[4], KEYS[5])
            return 1
        """, 6, index, self.coordinator.redis_key(ref.business_key), run, stream, done, cancel,
                            ref.run_id, ref.token_hash, ref.owner_uid, ref.owner_epoch,
                            ref.automation_generation, self.run_ttl, str(int(time.time())))
        if result != 1:
            raise SandboxCoordinationUnknown('Runtime stream reset no longer owns the admitted generation')

    def register_run(self, user_id, conversation_id, message_id=None, *, run_ref=None):
        ref = self._ref(user_id, conversation_id, run_ref)
        index, run, _, _, _ = self.keys(ref)
        result = self._call('eval', _CURRENT + _LEASE + """
            redis.call('HSET', KEYS[3], 'status', 'running', 'updated_at', ARGV[5])
            if ARGV[6] ~= '' then redis.call('HSET', KEYS[3], 'message_id', ARGV[6]) end
            redis.call('EXPIRE', KEYS[3], ARGV[7])
            return 1
        """, 3, index, self.coordinator.redis_key(ref.business_key), run,
                            ref.run_id, ref.token_hash, ref.owner_uid, ref.owner_epoch,
                            str(int(time.time())), str(message_id) if message_id is not None else '', self.run_ttl)
        if result != 1:
            raise SandboxCoordinationUnknown('Runtime registration lost its admitted generation')

    def get_run_state(self, user_id, conversation_id, *, run_ref=None):
        if run_ref is None:
            return {}
        ref = self._ref(user_id, conversation_id, run_ref)
        value = self._call('hgetall', self.keys(ref)[1]) or {}
        if not value and ref.phase != 'TERMINAL':
            raise SandboxCoordinationUnknown('Active Runtime state is missing; ownership remains unknown')
        return value

    def mark_run_finished(self, user_id, conversation_id, status, generation=None, *, run_ref=None):
        ref = self._ref(user_id, conversation_id, run_ref)
        _, run, stream, done, cancel = self.keys(ref)
        return self._call('eval', _CURRENT + """
            redis.call('HSET', KEYS[1], 'status', ARGV[2], 'updated_at', ARGV[3])
            for _, key in ipairs(KEYS) do redis.call('EXPIRE', key, ARGV[4]) end
            return 1
        """, 4, run, stream, done, cancel, ref.run_id, status, str(int(time.time())), self.completed_ttl)

    def set_cancel_signal(self, user_id, conversation_id, expected_generation=None, *, run_ref=None):
        if run_ref is None:
            return False
        ref = self._ref(user_id, conversation_id, run_ref)
        return bool(self._call('eval', """
            local indexed = redis.call('HGET', KEYS[1], 'generation')
            local leased = redis.call('HGET', KEYS[2], 'run_id')
            local current = indexed
            if ARGV[1] == '' then
                current = leased or indexed
            elseif leased == ARGV[4] and (ARGV[1] == ARGV[4] or ARGV[1] == ARGV[5]) then
                current = leased
            elseif indexed ~= ARGV[1]
               and redis.call('HGET', KEYS[1], 'automation_generation') ~= ARGV[1] then return 0 end
            if not current then return 0 end
            local run = ARGV[2] .. ':' .. current
            local status = redis.call('HGET', run, 'status')
            if current ~= leased and status ~= 'running' and status ~= 'preparing' then return 0 end
            redis.call('SETEX', run .. ':cancel', ARGV[3], current)
            return 1
        """, 2, self.keys(ref)[0], self.coordinator.redis_key(ref.business_key), expected_generation or '',
                               self._prefix(ref), self.cancel_ttl, ref.run_id, ref.automation_generation))

    def is_cancelled(self, user_id, conversation_id, *, run_ref=None):
        ref = self._ref(user_id, conversation_id, run_ref)
        return self._call('get', self.keys(ref)[4]) == ref.run_id

    def append_stream_event(self, user_id, conversation_id, chunk, *, run_ref=None):
        ref = self._ref(user_id, conversation_id, run_ref)
        index, _, stream, _, _ = self.keys(ref)
        result = self._call('eval', _CURRENT + """
            local id = redis.call('XADD', KEYS[2], 'MAXLEN', '~', ARGV[2], '*', 'chunk', ARGV[3])
            redis.call('EXPIRE', KEYS[2], ARGV[4])
            return id
        """, 2, index, stream, ref.run_id, self.max_stream_length, chunk, self.stream_ttl)
        return result if result else None

    def mark_stream_completed(self, user_id, conversation_id, status, error=None, *, run_ref=None):
        ref = self._ref(user_id, conversation_id, run_ref)
        _, run, stream, done, cancel = self.keys(ref)
        return self._call('eval', _CURRENT + """
            redis.call('HSET', KEYS[2], 'status', ARGV[2], 'updated_at', ARGV[3])
            if ARGV[4] ~= '' then redis.call('HSET', KEYS[2], 'error', ARGV[4]) end
            for _, key in ipairs(KEYS) do redis.call('EXPIRE', key, ARGV[5]) end
            return 1
        """, 4, run, done, stream, cancel, ref.run_id, status, str(int(time.time())), error or '', self.completed_ttl)

    def get_stream_status(self, user_id, conversation_id, *, run_ref=None):
        ref = self._ref(user_id, conversation_id, run_ref)
        return self._call('hgetall', self.keys(ref)[3]) or {}

    def read_stream_events(self, user_id, conversation_id, after_id=None, *, run_ref=None):
        ref = self._ref(user_id, conversation_id, run_ref)
        events = self._call('xrange', self.keys(ref)[2], min='-' if after_id is None else '(' + after_id)
        return [(event_id, values.get('chunk', '')) for event_id, values in events]

    def wait_for_stream_events(self, user_id, conversation_id, last_id, block_ms=1000, count=100, *, run_ref=None):
        ref = self._ref(user_id, conversation_id, run_ref)
        response = self._call('xread', {self.keys(ref)[2]: last_id}, count=count, block=block_ms)
        return [(event_id, values.get('chunk', '')) for _, events in response for event_id, values in events]

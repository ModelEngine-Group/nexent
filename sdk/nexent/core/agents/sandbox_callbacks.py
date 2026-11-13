# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Process-local callback capabilities, never persisted or shared between owners."""

import hashlib
import hmac
import threading


class SandboxCallbackContextError(ValueError):
    """A callback cannot refer to a closed invocation or an unexposed tool."""


class SandboxCallbackAuthorizationError(PermissionError):
    """A process-local callback capability is absent or has expired."""


class SandboxCallbackRegistry:
    def __init__(self, owner):
        self.owner = owner
        self._lock = threading.Lock()
        self._bridges = {}

    @staticmethod
    def _key(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def register(self, bridge):
        with self._lock:
            key = self._key(bridge._token)
            if key in self._bridges:
                raise RuntimeError('Sandbox callback capability is already registered')
            self._bridges[key] = bridge

    def unregister(self, bridge):
        with self._lock:
            key = self._key(bridge._token)
            if self._bridges.get(key) is bridge:
                del self._bridges[key]

    def authorize(self, authorization):
        if not isinstance(authorization, str) or not authorization.startswith('Bearer ') or len(authorization) > 128:
            raise SandboxCallbackAuthorizationError('Invalid sandbox callback capability')
        token = authorization[7:]
        with self._lock:
            bridge = self._bridges.get(self._key(token))
            if bridge is None or not hmac.compare_digest(token, bridge._token) or bridge._closed:
                raise SandboxCallbackAuthorizationError('Invalid sandbox callback capability')
            return bridge

    def invoke(self, authorization, payload):
        bridge = self.authorize(authorization)
        lifecycle = getattr(bridge, '_runtime_lifecycle', None)
        holder = lifecycle.begin('callback') if lifecycle is not None else None
        try:
            return bridge._invoke_tool(payload)
        finally:
            if holder is not None:
                lifecycle.finish(holder)

# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Finite trusted grants may address an opaque S3 key without rewriting it."""

from nexent.storage.errors import InvalidInput, ScopeDenied

from infrastructure.object_storage.port import S3ObjectStore


def opaque_key(value):
    try:
        valid = isinstance(value, str) and 0 < len(value.encode('utf-8')) <= 1024 and '\x00' not in value
    except UnicodeError:
        valid = False
    if not valid:
        raise InvalidInput()
    return value


class ExactKeyObjectStore(S3ObjectStore):
    def __init__(self, scope, binding, client_factory):
        if binding.exact_keys is None or binding.prefix or scope.resource_prefix:
            raise ScopeDenied()
        super().__init__(scope, binding, client_factory)

    def _target(self, ref, *, write=False):
        binding = self._binding
        if (ref.space != binding.space or binding.exact_keys is None or binding.prefix
            or self.scope.resource_prefix or ref.key not in binding.exact_keys
            or write and not binding.writable):
            raise ScopeDenied()
        return {'Bucket': binding.bucket, 'Key': opaque_key(ref.key)}

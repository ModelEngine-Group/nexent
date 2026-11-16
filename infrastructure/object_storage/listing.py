# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bounded current-object enumeration with logical, query-bound cursors."""

import base64
import hashlib
import json

from nexent.storage.errors import CapabilityUnsupported, InvalidInput, Unavailable
from nexent.storage.models import ObjectMetadata, ObjectRef, Page, PageRequest, Revision

_MAX_CURSOR = 16384


def _fingerprint(store, prefix, limit):
    binding, scope = store._binding, store.scope
    data = [
        binding.space,
        binding.bucket,
        binding.prefix,
        scope.service_role,
        scope.tenant_id,
        scope.actor_id,
        scope.system,
        scope.resource_prefix,
        prefix,
        limit,
    ]
    return hashlib.sha256(json.dumps(data, separators=(",", ":")).encode()).hexdigest()


def _cursor(token, fingerprint):
    return base64.urlsafe_b64encode(
        json.dumps(
            {"v": 1, "query": fingerprint, "next": token}, separators=(",", ":")
        ).encode()
    ).decode()


def _token(cursor, fingerprint):
    if cursor is None:
        return None
    try:
        if not isinstance(cursor, str) or not cursor or len(cursor) > _MAX_CURSOR:
            raise ValueError()
        data = json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
        if (
            not isinstance(data, dict)
            or type(data.get("v")) is not int
            or data["v"] != 1
            or data.get("query") != fingerprint
            or not isinstance(data.get("next"), str)
            or not data["next"]
        ):
            raise ValueError()
        return data["next"]
    except (ValueError, TypeError, KeyError):
        raise InvalidInput() from None


def list_objects(store, prefix, page, *, context):
    from infrastructure.object_storage.port import _key

    # Finite legacy grants must never issue bucket-enumeration requests.
    if store._binding.exact_keys is not None:
        raise CapabilityUnsupported(operation_id=context.operation_id)
    if not isinstance(page, PageRequest) or not isinstance(prefix, str):
        raise InvalidInput(operation_id=context.operation_id)
    if prefix:
        _key(prefix.removesuffix("/"))
    # Derive the same root used by point operations; caller input cannot replace it.
    root = store._target(ObjectRef(store._binding.space, "scope-marker"))["Key"]
    root = root.removesuffix("scope-marker")
    fingerprint = _fingerprint(store, prefix, page.limit)
    token = _token(page.cursor, fingerprint)
    arguments = {
        "Bucket": store._binding.bucket,
        "Prefix": root + prefix,
        "MaxKeys": page.limit,
    }
    if token is not None:
        arguments["ContinuationToken"] = token
    with store._client(context) as client:
        response = store._call(client, "list_objects_v2", context, **arguments)
        try:
            contents = response.get("Contents", [])
            truncated = response.get("IsTruncated", False)
            if (
                not isinstance(contents, list)
                or len(contents) > page.limit
                or type(truncated) is not bool
            ):
                raise ValueError()
            values, seen = [], set()
            for item in contents:
                key, size, etag = item["Key"], item["Size"], item["ETag"]
                if (
                    not isinstance(key, str)
                    or not key.startswith(root + prefix)
                    or type(size) is not int
                    or size < 0
                    or not isinstance(etag, str)
                    or not etag
                    or key in seen
                ):
                    raise ValueError()
                seen.add(key)
                logical = key[len(root) :]
                if logical.endswith("/"):
                    # S3 console folder markers have no valid point-operation key.
                    _key(logical[:-1])
                    continue
                _key(logical)
                values.append(
                    ObjectMetadata(
                        ObjectRef(
                            store._binding.space, logical, Revision("etag:" + etag)
                        ),
                        size,
                        "application/octet-stream",
                        etag,
                    )
                )
            next_cursor = None
            if truncated:
                next_token = response["NextContinuationToken"]
                if (
                    not isinstance(next_token, str)
                    or not next_token
                    or next_token == token
                ):
                    raise ValueError()
                next_cursor = _cursor(next_token, fingerprint)
                if len(next_cursor) > _MAX_CURSOR:
                    raise ValueError()
            return Page(tuple(values), next_cursor)
        except (KeyError, ValueError, TypeError, InvalidInput):
            raise Unavailable(operation_id=context.operation_id) from None

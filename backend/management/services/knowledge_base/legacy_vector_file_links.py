# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Relate historical parsed records to exact lifecycle rows without opening any source."""

from collections import defaultdict
from urllib.parse import urlsplit

from contracts.knowledge_ingestion import ACTIVE_LEGACY_FILE_IDS, is_historical_file_id
from contracts.knowledge_maintenance import LegacyVectorFileLink
from nexent.storage.errors import Conflict, ScopeDenied
from nexent.storage.models import Comparison, Junction, PageRequest, RecordQuery

FILE_LINK_FIELDS = (
    'file_id', 'public_file_id', 'tenant_id', 'knowledge_id', 'index_name', 'bucket_name',
    'source_key', 'object_name', 'local_source_path', 'delete_flag', 'deletion_request',
    'status', 'source_generation', 'version',
)


def _object_key(value, bucket):
    if not value:
        return None
    if '://' in value:
        try:
            parsed = urlsplit(value)
        except ValueError:
            return None
        if (parsed.scheme != 's3' or parsed.netloc != bucket or not parsed.path.startswith('/')
            or value != f's3://{bucket}{parsed.path}'):
            return None
        value = parsed.path[1:]
    elif bucket and value.startswith(f"/{bucket}/"):
        value = value[len(bucket) + 2:]
    if value and not value.startswith('/') and not any(part in {'', '.', '..'} for part in value.split('/')):
        return value
    return None


def legacy_chunk_position(source):
    metadata = source.get('metadata')
    position = source.get('index')
    if position is None and isinstance(metadata, dict):
        position = metadata.get('chunk_index')
    return position if type(position) is int and position >= 0 else None


def legacy_source_addresses(row, *, strict=False):
    """Enumerate the exact historical spellings of one recorded source."""
    bucket = row["bucket_name"]
    objects = {_object_key(row[name], bucket) for name in ("object_name", "source_key")}
    result = {key for key in objects if key}
    local = row["local_source_path"]
    if strict and (len(result) > 1 or any(
            row[name] and row[name] != local and _object_key(row[name], bucket) is None for name in ("object_name", "source_key")
        )):
        raise Conflict()
    if bucket:
        for key in tuple(result):
            result.update((f"s3://{bucket}/{key}", f"/{bucket}/{key}"))
    if local:
        result.add(local)
    return result


def require_unique_source_addresses(records, knowledge_id, addresses, *, context, file_id=None):
    # Include retired rows. A reused source path can still identify historical vectors.
    cursor = None
    query = RecordQuery(where=Comparison("knowledge_id", "eq", knowledge_id),
                        fields=("file_id", "bucket_name", "source_key", "object_name", "local_source_path"))
    while True:
        page = records.query("knowledge_file_history", query, PageRequest(limit=500, cursor=cursor), context=context)
        for row in page.items:
            raw_addresses = {row[field] for field in ("source_key", "object_name", "local_source_path")}
            if row["file_id"] != file_id and addresses & (legacy_source_addresses(row) | raw_addresses):
                raise Conflict()
        cursor = page.next_cursor
        if cursor is None:
            return


def active_file_alias(records, knowledge_id, file_id, *, context):
    query = RecordQuery(where=Junction("and", (Comparison("knowledge_id", "eq", knowledge_id),
                                               Comparison("standard_file_id", "eq", file_id))))
    page = records.query(ACTIVE_LEGACY_FILE_IDS, query, PageRequest(limit=2), context=context)
    if not page.items:
        return None
    if page.next_cursor or len(page.items) != 1:
        raise Conflict()
    row = page.items[0]
    alias = row["original_file_id"]
    if (row["knowledge_id"] != knowledge_id or row["standard_file_id"] != file_id
        or row["tenant_id"] != records.scope.tenant_id or alias == file_id or not is_historical_file_id(alias)):
        raise ScopeDenied()
    return alias


class LegacyVectorFileLinks:
    def __init__(self, rows, knowledge, actor):
        self.rows = {}
        self.by_id = defaultdict(set)
        self.by_address = defaultdict(set)
        self.conflicting = set()
        for row in rows:
            if (row['tenant_id'] != actor.tenant_id or row['knowledge_id'] != knowledge['knowledge_id']
                or row['index_name'] != knowledge['index_name']):
                raise ScopeDenied()
            file_id = row['file_id']
            if not is_historical_file_id(file_id) or file_id in self.rows:
                raise Conflict()
            self.rows[file_id] = row
            self.by_id[file_id].add(file_id)
            if is_historical_file_id(row['public_file_id']):
                self.by_id[row['public_file_id']].add(file_id)
            bucket = row['bucket_name']
            source_key = _object_key(row['source_key'], bucket)
            object_key = _object_key(row['object_name'], bucket)
            keys = {key for key in (source_key, object_key) if key}
            local = row['local_source_path']
            if (len(keys) > 1 or row['source_key'] and source_key is None
                or row['object_name'] and object_key is None and row['object_name'] != local):
                self.conflicting.add(file_id)
            # Retired rows still make a reused address ambiguous.
            for key in keys:
                self.by_address[key].add(file_id)
                if bucket:
                    self.by_address[f's3://{bucket}/{key}'].add(file_id)
                    self.by_address[f'/{bucket}/{key}'].add(file_id)
            if local and '://' not in local:
                self.by_address[local].add(file_id)

    def find(self, source, tenant_id):
        metadata = source.get('metadata')
        if metadata is not None and not isinstance(metadata, dict):
            return LegacyVectorFileLink(status='unresolved')
        fields = (source, metadata or {})
        if any(part.get('tenant_id') not in (None, tenant_id) for part in fields):
            return LegacyVectorFileLink(status='conflict')
        raw_ids = [part['file_id'] for part in fields if part.get('file_id') is not None]
        origin = source.get('process_source')
        parsed = legacy_chunk_position(source) is not None and isinstance(origin, str) and bool(origin.strip())
        if not raw_ids and not parsed:
            return LegacyVectorFileLink(status='unresolved')
        address = source.get('path_or_url')
        if address is not None and not isinstance(address, str):
            return LegacyVectorFileLink(status='conflict')
        by_address = self.by_address.get(address, set()) if isinstance(address, str) and address else set()
        evidence = [self.by_id.get(value, set()) if is_historical_file_id(value) else set() for value in raw_ids]
        if not raw_ids or address:
            evidence.append(by_address)
        if any(len(matches) > 1 for matches in evidence):
            return LegacyVectorFileLink(status='ambiguous')
        matches = set().union(*evidence)
        if matches and (len(matches) != 1 or not all(evidence)):
            return LegacyVectorFileLink(status='conflict')
        if not matches:
            return LegacyVectorFileLink(status='unresolved')
        file_id = matches.pop()
        if file_id in self.conflicting:
            return LegacyVectorFileLink(status='conflict')
        row = self.rows[file_id]
        if (row['delete_flag'] != 'N' or row['deletion_request'] is not None
            or row['status'] not in {'UPLOADED', 'FAILED', 'COMPLETED'}
            or any(type(row[name]) is not int or row[name] < 0 for name in ('source_generation', 'version'))):
            return LegacyVectorFileLink(status='unresolved')
        return LegacyVectorFileLink(status='matched', file_id=row['file_id'],
            via='file_id' if raw_ids else 'source_address', source_generation=row['source_generation'],
            lifecycle_revision=row['version'])

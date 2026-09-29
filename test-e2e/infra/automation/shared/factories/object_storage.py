"""Journal exact UUID object keys for audited in-process recovery tests."""
from contextlib import contextmanager, ExitStack
import json
import os
import re
import subprocess
from unittest.mock import patch
from shared.asset_registry import register_asset, mark_asset_state, AssetDependencyError


_OWNED_KEY = re.compile(r'(?:d5-recovery/[0-9a-f]{32}\.bin|rel_auto_upload_recovery/[0-9a-f]{32}/[ab]\.bin)\Z')


def _inspect(container):
    result = subprocess.run(['docker', 'inspect', container], capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise AssetDependencyError('storage', 'minio', detail='Cannot inspect configured storage deployment')
    return json.loads(result.stdout)[0]


@contextmanager
def configured_product_storage():
    """Resolve the test host endpoint; never assume container DNS works on host."""
    from database import client as product
    required = ('MINIO_ENDPOINT','MINIO_ACCESS_KEY','MINIO_SECRET_KEY','MINIO_DEFAULT_BUCKET')
    values = {key: os.environ.get(key, '') for key in (*required, 'MINIO_REGION')}
    if not all(values[key] for key in required):
        config = _inspect(os.getenv('NEXENT_TEST_CONFIG_CONTAINER', 'nexent-config'))
        deployed = dict(row.split('=', 1) for row in config['Config'].get('Env', []) if '=' in row)
        for key in values:
            values[key] = values[key] or deployed.get(key, '')
        if not os.environ.get('MINIO_ENDPOINT'):
            endpoint = os.environ.get('NEXENT_TEST_MINIO_ENDPOINT')
            if not endpoint:
                storage = _inspect(os.getenv('NEXENT_TEST_MINIO_CONTAINER', 'nexent-minio'))
                addresses = {v.get('IPAddress') for v in storage['NetworkSettings']['Networks'].values() if v.get('IPAddress')}
                if len(addresses) != 1:
                    raise AssetDependencyError('storage','minio',detail='Set NEXENT_TEST_MINIO_ENDPOINT for ambiguous network')
                endpoint = 'http://' + addresses.pop() + ':9000'
            values['MINIO_ENDPOINT'] = endpoint
    if not all(values[key] for key in required):
        raise AssetDependencyError('storage','minio',detail='Required storage configuration is incomplete')
    storage = product.minio_client
    with ExitStack() as stack:
        for key, value in values.items(): stack.enter_context(patch.object(product, key, value))
        stack.enter_context(patch.object(storage, '_storage_client', None))
        stack.enter_context(patch.object(storage, 'storage_config', None))
        storage._ensure_initialized()
        yield storage


def strict_exists(storage, key, bucket):
    # Product exists() converts every S3 ClientError (including 403) to False.
    # That is not sufficient evidence of absence for destructive cleanup.
    storage._ensure_initialized()
    try:
        storage._storage_client.client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception as exc:
        code = str(getattr(exc, 'response', {}).get('Error', {}).get('Code', ''))
        if code in {'404', 'NoSuchKey', 'NotFound'}:
            return False
        raise


def delete_owned_object(storage, bucket, key, *, exists=None, delete=None):
    if not _OWNED_KEY.fullmatch(key):
        raise ValueError('Object key is outside audited recovery factory scope')
    exists = exists or (lambda key, bucket: strict_exists(storage, key, bucket))
    delete = delete or storage.delete_file
    if exists(key, bucket):
        delete(key, bucket)
    if exists(key, bucket):
        raise RuntimeError('Owned object remains after cleanup')


@contextmanager
def owned_recovery_objects(storage):
    """Preserve real MinIO I/O; intercept ownership, never response/assertions."""
    upload, delete = storage.upload_fileobj, storage.delete_file
    exists = lambda key, bucket: strict_exists(storage, key, bucket)
    owned = {}
    primary = None

    def tracked_upload(fileobj, object_name, bucket=None, *args, **kwargs):
        bucket = bucket or storage.default_bucket
        if not _OWNED_KEY.fullmatch(object_name):
            raise ValueError('Unexpected object key in recovery fixture')
        entry_key = bucket + '/' + object_name
        if entry_key not in owned:
            if exists(object_name, bucket):
                raise RuntimeError('Refusing to overwrite a preexisting object')
            # Register the reserved key before I/O, including ambiguous upload failure.
            owned[entry_key] = (bucket, object_name)
            register_asset('owned_recovery_objects', entry_key, object_name,
                owner_case_id='RECOVERY-OBJECT-FACTORY', cleanup={
                    'kind': 'delete_recovery_object', 'bucket': bucket, 'object_name': object_name})
        return upload(fileobj, object_name, bucket, *args, **kwargs)

    try:
        with patch.object(storage, 'upload_fileobj', tracked_upload):
            yield
    except BaseException as exc:
        primary = exc
        raise
    finally:
        failures = []
        for entry_key, (bucket, key) in reversed(list(owned.items())):
            try:
                # Ignore test-local injected failures in file_exists/delete_file.
                delete_owned_object(storage, bucket, key, exists=exists, delete=delete)
                mark_asset_state('owned_recovery_objects', entry_key, 'DELETED')
            except Exception as exc:
                failures.append(type(exc).__name__)
                mark_asset_state('owned_recovery_objects', entry_key, 'ORPHANED', detail=type(exc).__name__)
        if failures:
            message = 'Owned recovery object cleanup failed; see asset journal'
            if primary is None: raise RuntimeError(message)
            if hasattr(primary, 'add_note'): primary.add_note(message)
            else: primary.__notes__ = [*getattr(primary, '__notes__', []), message]

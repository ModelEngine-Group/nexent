"""Create only the performance resources needed by the selected target."""
from shared.asset_registry import register_asset, AssetDependencyError
from d3.assets import asset_path, create_registered_knowledge_base
from .files import upload_attachment_bytes


async def prepare_upload_target(identity):
    source=asset_path('files','large_document')
    if not source.is_file() or source.stat().st_size==0:
        raise AssetDependencyError('files','large_document',detail='Configured nonempty large document required')
    kb=await create_registered_knowledge_base(identity,owner_case_id='PERFORMANCE-UPLOAD-PREP',
                                               role='performance_upload',prefix='perf-upload')
    register_asset('performance','upload_kb_index',kb['index_name'],owner_case_id='PERFORMANCE-UPLOAD-PREP')
    return kb['index_name']


async def prepare_range_attachment(identity):
    # Range correctness requires four complete 64-KiB ranges, not a business
    # document. Generate an explicit deterministic fixture; do not enlarge or
    # replace the shared large_document asset used by upload benchmarks.
    from uuid import uuid4
    line=b'Nexent isolated HTTP Range fixture.\n'
    content=(line*((262144+len(line)-1)//len(line)))[:262144]
    object_name=await upload_attachment_bytes(identity,'range-'+uuid4().hex+'.txt',content,'text/plain')
    from urllib.parse import quote
    from shared.http import client,assert_status
    async with client('config',token=identity.access_token) as api:
        stored=await api.get(f'/file/download/{quote(object_name,safe="/")}',params={'download':'stream'})
    assert_status(stored,200)
    if stored.content!=content:
        raise AssetDependencyError('performance','large_attachment_object_name',detail='Uploaded range fixture content mismatch')
    register_asset('performance','large_attachment_object_name',object_name,owner_case_id='PERFORMANCE-RANGE-PREP')
    return object_name

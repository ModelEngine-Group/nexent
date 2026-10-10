"""Owned tag-assignment resources; no historical first-row selection."""
from uuid import uuid4
from shared.asset_registry import register_asset, resolve_asset
from shared.http import client, assert_status, MODEL_TIMEOUT
from shared.factories.agent import _draft_agent
from shared.factories.skill import prepare_skill
from shared.factories.files import _upload_kb_file
from shared.factories.readiness import wait_ready

OWNER='LOCAL-TAG-PREP'


def register_tag_definition(identity, bucket_id, definition):
    """Journal ownership before assignment/assertions; keys are tenant-specific."""
    from shared.factories.ownership import register_owned_http
    definition_id=definition['definition_id']
    register_owned_http(identity,'tag_definitions',definition_id,
                        f'/tag-libraries/{bucket_id}/definitions/{definition_id}')
    for value in definition.get('values',[]):
        value_id=value['value_id']
        register_owned_http(identity,'tag_values',value_id,
                            f'/tag-libraries/{bucket_id}/definitions/{definition_id}/values/{value_id}')


async def prepare_tag_definitions(identity):
    async with client('config',token=identity.access_token) as api:
        response=await api.get('/tag-libraries')
        assert_status(response,200)
        buckets={b['bucket_key']:b for b in response.json()}
        bucket=buckets['default_resource']['bucket_id']
        for mode in ('multi_select','single_select'):
            name='isolated-'+uuid4().hex
            response=await api.post(f'/tag-libraries/{bucket}/definitions',json={
                'definition_key':name,'definition_name':name,'selection_mode':mode,
                'initial_values':['first','second']})
            assert_status(response,200)
            definition=response.json()
            definition_id=definition['definition_id']
            register_asset('tag_definitions',mode,definition_id,owner_case_id=OWNER,cleanup={
                'service':'config','identity':identity.id,'method':'DELETE',
                'path':f'/tag-libraries/{bucket}/definitions/{definition_id}',
                'allowed_statuses':[200,404]})
            for value in definition['values']:
                value_id=value['value_id']
                register_asset('tag_values',f'{mode}_{value_id}',value_id,owner_case_id=OWNER,cleanup={
                    'service':'config','identity':identity.id,'method':'DELETE',
                    'path':f'/tag-libraries/{bucket}/definitions/{definition_id}/values/{value_id}',
                    'allowed_statuses':[200,404]})
            if len([v for v in definition['values'] if v['status']=='active'])!=2:
                raise AssertionError('tag fixture requires two active values')


async def prepare_tag_resources(identity):
    # Definitions precede resources so cleanup removes assignments/resources
    # before attempting to delete definitions still in use.
    await prepare_tag_definitions(identity)
    def bind(kind,value):
        register_asset('tag_assignments',kind,value,owner_case_id=OWNER)
    async with _draft_agent(identity,name_prefix='tag-agent',retain_for_batch=True,
                            owner_case_id=OWNER,registry_role='tag',cleanup_identity=identity.id) as (agent,_):
        bind('agent',agent)
    await prepare_skill(identity,role='configurable',cleanup_identity=identity.id,owner=OWNER)
    bind('skill',resolve_asset('skills','configurable_id',required=True))
    from prepare_d4_shared_assets import _ensure_controlled_mcp_service, _controlled_tool_id
    service,_=await _ensure_controlled_mcp_service(identity)
    bind('mcp_service',service)
    bind('tool',await _controlled_tool_id(identity,'deterministic_add'))
    from d3.assets import create_registered_knowledge_base
    kb=await create_registered_knowledge_base(identity,owner_case_id=OWNER,role='tag',prefix='tag-kb')
    index=kb['index_name']
    bind('knowledge_base',index)
    uploaded=await _upload_kb_file(identity,index)
    path=uploaded['object_name']
    from shared.factories.knowledge import create_kb_chunk
    await create_kb_chunk(identity,index,'Isolated tag assignment document',title='Tag fixture',
                          filename='tag-fixture.txt',path_or_url=path)
    async def read():
        async with client('config',token=identity.access_token) as api:
            response=await api.get(f'/indices/{index}/files')
        assert_status(response,200)
        found=any(str(f.get('path_or_url'))==path for f in response.json().get('files',[]))
        return ('READY' if found else 'PENDING'),found
    await wait_ready(read,ready={'READY'},failed={'FAILED'},timeout=30,interval=1,
                     section='tag_assignments',key='knowledge_document')
    bind('knowledge_document',{'resource_id':path,'provider':'local','knowledge_base_id':index})


def select_owned_definitions(definitions,mode):
    """Keep Daily compatibility; local factory always pins its own definition."""
    owned=resolve_asset('tag_definitions',mode,required=False)
    rows=[d for d in definitions if d['selection_mode']==mode and d.get('values')]
    if owned is not None:
        rows=[d for d in rows if str(d['definition_id'])==str(owned)]
        if len(rows)!=1: raise AssertionError('owned tag definition missing from read-back')
    return rows

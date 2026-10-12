"""Reconcile partial KB creation using exact, batch-unique ownership only."""
from shared.asset_registry import register_asset
from shared.http import client,assert_status,MODEL_TIMEOUT


async def cleanup_registered_knowledge_files(identity,index_name):
    """Remove only this batch's registered files in this exact owned index."""
    from shared.asset_registry import all_registered_assets,mark_asset_state
    for key,entry in all_registered_assets().get('knowledge_files',{}).items():
        cleanup=entry.get('cleanup') or {}
        if entry.get('source')!='dynamic' or entry.get('state')=='DELETED':continue
        if str(cleanup.get('path','')).split('?',1)[0]!=f'/indices/{index_name}/documents':continue
        if cleanup.get('identity')!=identity.id:
            raise RuntimeError('knowledge file cleanup identity mismatch')
        async with client('config',token=identity.access_token) as api:
            removed=await api.delete(cleanup['path'])
        assert_status(removed,(200,404))
        mark_asset_state('knowledge_files',key,'DELETED')


async def create_kb_chunk(identity,index_name,content,*,title,filename,path_or_url=None):
    payload={'content':content,'title':title,'filename':filename}
    if path_or_url is not None:payload['path_or_url']=path_or_url
    async with client('config',token=identity.access_token,timeout=MODEL_TIMEOUT) as api:
        response=await api.post(f'/indices/{index_name}/chunk',json=payload)
    assert_status(response,200)
    chunk_id=response.json().get('chunk_id')
    if not chunk_id:raise AssertionError('manual chunk creation omitted chunk_id')
    return str(chunk_id)


def register_partial_knowledge(identity, name, *, owner, role):
    # The API can insert its DB record before ES rejects creation. Do not parse
    # arbitrary error strings as IDs or enumerate unrelated tenant resources.
    from shared.factories.sharing import product_db
    product_db()
    from database.client import get_db_session
    from database.db_models import KnowledgeRecord
    from sqlalchemy import select
    with get_db_session() as session:
        records=session.execute(select(KnowledgeRecord).where(
            KnowledgeRecord.knowledge_name==name,
            KnowledgeRecord.tenant_id==str(identity.tenant_id),
            KnowledgeRecord.created_by==str(identity.user_id),
            KnowledgeRecord.delete_flag=='N',
        )).scalars().all()
        indices=[r.index_name for r in records]
    if len(indices)>1:
        raise RuntimeError('ambiguous partial KB ownership; refusing cleanup')
    for index in indices:
        register_asset('knowledge',role+'_partial_index',index,owner_case_id=owner,state='FAILED',cleanup={
            'service':'config','identity':identity.id,'method':'DELETE',
            'path':f'/indices/{index}','allowed_statuses':[200,404]})
    return indices

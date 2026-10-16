"""Fresh Agent listing for import consumers, never borrow marketplace rows."""
from shared.factories.agent import _draft_agent, _llm_id
from shared.asset_registry import register_asset
from shared.http import assert_status,client


async def prepare_agent_listing(author,reviewer):
    owner='LOCAL-REPOSITORY-PREP'
    if author.tenant_id != reviewer.tenant_id:
        raise ValueError('Agent listing author and reviewer must belong to the same tenant')
    # Model health requires model:update. Probe with the existing tenant
    # administrator, but retain the developer for every author operation.
    model_id = await _llm_id(reviewer)
    async with _draft_agent(author,name_prefix='local-market',retain_for_batch=True,
                            owner_case_id=owner,registry_role='market_source',cleanup_identity=author.id,
                            model_ids=[model_id]) as (agent,_):
        async with client('config',token=author.access_token) as api:
            published=await api.post(f'/agent/{agent}/publish',json={'version_name':'isolated-import','release_note':'isolated fixture'})
            assert_status(published,200)
            version=int(published.json()['version_no'])
            listed=await api.post(f'/repository/agent/{agent}/versions/{version}',json={
                'icon':'automation-agent','tags':['automation'],'content':'Isolated import fixture'})
            assert_status(listed,200)
            listing=int(listed.json()['agent_repository_id'])
            register_asset('repository','agent_listing_id',listing,owner_case_id=owner,cleanup={
                'service':'config','identity':reviewer.id,'method':'PATCH',
                'path':f'/repository/agent/{listing}/status','json':{'status':'not_shared'},'allowed_statuses':[200,404]})
            submitted=await api.patch(f'/repository/agent/{listing}/status',json={'status':'pending_review'})
            assert_status(submitted,200)
        async with client('config',token=reviewer.access_token) as api:
            approved=await api.patch(f'/repository/agent/{listing}/status',json={'status':'shared'})
            assert_status(approved,200)
            detail=await api.get(f'/repository/agent/{listing}')
            assert_status(detail,200)
        return listing

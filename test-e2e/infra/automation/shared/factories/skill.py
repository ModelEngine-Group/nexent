"""Extracted asset operations; scenario assertions remain in the test modules."""
from __future__ import annotations
from shared.http import assert_status, client
import uuid


def _skill_payload(name: str) -> dict:
    content = f"---\nname: {name}\ndescription: automated contract skill\n---\n\n# {name}\n"
    return {
        "name": name,
        "description": "automated contract skill",
        "content": content,
        "tags": ["automation"],
        "source": "custom",
        "files": [{"path": "references/check.txt", "content": "contract-asset"}],
    }


async def _create_skill(identity, prefix: str = "contract", *, exact_name: str | None = None) -> dict:
    name = exact_name or f"{prefix}-{uuid.uuid4().hex[:10]}"
    async with client("config", token=identity.access_token) as api:
        response = await api.post("/skills", json=_skill_payload(name))
    assert_status(response, 201)
    from shared.asset_registry import runtime_dir
    from shared.factories.ownership import register_owned_http
    if runtime_dir() is not None:
        register_owned_http(identity,'owned_skills',name,f'/skills/{name}')
    return response.json()


async def _delete_skill(identity, name: str) -> None:
    async with client("config", token=identity.access_token) as api:
        response = await api.delete(f"/skills/{name}")
    if response.status_code==400:
        async with client('config',token=identity.access_token) as api:
            absent=await api.get(f'/skills/{name}')
        assert_status(absent,404)
    else:
        assert_status(response,(200,404))
    from shared.asset_registry import mark_asset_state
    mark_asset_state('owned_skills',name,'DELETED')


async def prepare_skill(identity, *, role: str, cleanup_identity: str, owner: str):
    """Create a fresh owned Skill; do not depend on PW-SKILL-01/API-077."""
    from shared.asset_registry import register_asset, all_registered_assets
    if role not in {'configurable', 'd4_created'}:
        raise ValueError('unsupported skill role')
    current=all_registered_assets().get('skills',{})
    existing_id=current.get(role+'_id',{})
    existing_name=current.get(role+'_name',{})
    if existing_id.get('state')=='READY' and existing_name.get('state')=='READY':
        name=str(existing_name['value'])
        async with client('config',token=identity.access_token) as api:
            verified=await api.get(f'/skills/{name}')
        assert_status(verified,200)
        body=verified.json()
        if body.get('name')!=name or int(body.get('skill_id') or body.get('id') or 0)!=int(existing_id['value']):
            raise AssertionError('current-batch Skill identity changed; refusing to overwrite cleanup ownership')
        return name
    created = await _create_skill(identity, 'local-skill')
    name, skill_id = str(created['name']), int(created['skill_id'])
    register_asset('skills', role+'_id', skill_id, owner_case_id=owner, cleanup={
        'service':'config', 'identity':cleanup_identity, 'method':'DELETE',
        'path':f'/skills/{name}', 'allowed_statuses':[200,404],
    })
    register_asset('skills', role+'_name', name, owner_case_id=owner)
    async with client('config', token=identity.access_token) as api:
        verified = await api.get(f'/skills/{name}')
    assert_status(verified, 200)
    if verified.json().get('name') != name:
        raise AssertionError('created Skill name differs from read-back')
    return name


async def prepare_skill_agent(author,consumer):
    from shared.factories.agent import _draft_agent
    from shared.asset_registry import resolve_asset
    owner='LOCAL-SKILL-AGENT-PREP'
    await prepare_skill(author,role='configurable',cleanup_identity=author.id,owner=owner)
    skill_id=int(resolve_asset('skills','configurable_id',required=True))
    async with _draft_agent(consumer,name_prefix='local-skill-agent',retain_for_batch=True,
                            owner_case_id=owner,registry_role='skill',cleanup_identity=consumer.id) as (agent,payload):
        async with client('config',token=consumer.access_token) as api:
            bound=await api.post('/agent/update',json={**payload,'enabled_skill_ids':[skill_id],
                'skill_instances':[{'skill_id':skill_id,'enabled':True,'config_values':{}}]})
            assert_status(bound,200)
            read=await api.get('/skills/instance/list',params={'agent_id':agent,'version_no':0})
            assert_status(read,200)
        return agent

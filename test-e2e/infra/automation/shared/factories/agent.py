"""Extracted asset operations; scenario assertions remain in the test modules."""
from __future__ import annotations
from shared.http import assert_status, client
import uuid
from contextlib import asynccontextmanager
from d3.assets import model_id as configured_model_id
from shared.asset_registry import register_asset, mark_asset_state, AssetDependencyError


@asynccontextmanager
async def retrieval_agent(identity):
    """Own an Agent with the actual built-in knowledge search tool enabled.

    The request's knowledge_scope carries the current test's KB IDs; never
    borrow an Agent whose saved scope may point at a previous batch's KB.
    """
    async with client('config',token=identity.access_token) as api:
        response = await api.get('/tool/list')
    assert_status(response,200)
    matches = [row for row in response.json()
               if row.get('origin_name') == 'knowledge_base_search' and row.get('source') != 'mcp']
    if len(matches) != 1:
        raise AssetDependencyError('tools','knowledge_base_search',detail='Expected one built-in retrieval tool')
    tool_id = int(matches[0].get('tool_id') or matches[0]['id'])
    async with _draft_agent(identity,name_prefix='owned-retrieval',enabled_tool_ids=[tool_id]) as (agent_id,_):
        yield agent_id


async def _delete_draft(identity, agent_id):
    async with client('config',token=identity.access_token) as api:
        response = await api.request('DELETE','/agent',json={'agent_id':agent_id})
    assert_status(response,(200,404))
    mark_asset_state('owned_agents',str(agent_id),'DELETED')


async def _llm_id(identity) -> int:
    return int(await configured_model_id("llm", identity))


async def prepare_basic_agent(identity):
    """Produce the retained published Agent without running API-055 assertions."""
    async with _draft_agent(identity,retain_for_batch=True,owner_case_id='LOCAL-BASIC-PREP',
                            registry_role='basic',cleanup_identity=identity.id,
                            allow_chat_metadata=True) as (agent_id,_):
        async with client('config',token=identity.access_token) as api:
            response=await api.post('/agent/search_info',json={'agent_id':agent_id,'version_no':0})
        assert_status(response,200)
        body=response.json().get('data') or response.json()
        if int(body.get('agent_id') or body.get('id') or 0)!=agent_id:
            raise AssertionError('basic Agent read-back identity mismatch')
        if body.get('allow_chat_metadata') is not True:
            raise AssetDependencyError('agents', 'basic_id', detail='Basic Agent did not persist metadata opt-in')
        return agent_id


async def prepare_metadata_agent(identity):
    """Metadata consumers require a persisted opt-in, not a basic-Agent alias."""
    async with _draft_agent(identity,retain_for_batch=True,owner_case_id='LOCAL-METADATA-PREP',
                            registry_role='metadata',cleanup_identity=identity.id,
                            allow_chat_metadata=True) as (agent_id,_):
        async with client('config',token=identity.access_token) as api:
            response=await api.post('/agent/search_info',json={'agent_id':agent_id,'version_no':0})
        assert_status(response,200)
        body=response.json().get('data') or response.json()
        if body.get('allow_chat_metadata') is not True:
            raise AssetDependencyError('agents','metadata_id',detail='Created Agent did not retain metadata opt-in')
        return agent_id


async def prepare_relationship_agent(identity):
    """Own the parent and both children needed by nested/parallel runtime cases."""
    owner = 'LOCAL-RELATIONSHIP-PREP'
    async with _draft_agent(identity, name_prefix='local-parent', retain_for_batch=True,
                            owner_case_id=owner, registry_role='relationship_parent',
                            cleanup_identity=identity.id) as (parent_id, parent):
        async with _draft_agent(identity, name_prefix='local-child-a', retain_for_batch=True,
                                owner_case_id=owner, registry_role='relationship_child_a',
                                cleanup_identity=identity.id) as (child_a_id, _):
            async with _draft_agent(identity, name_prefix='local-child-b', retain_for_batch=True,
                                    owner_case_id=owner, registry_role='relationship_child_b',
                                    cleanup_identity=identity.id) as (child_b_id, _):
                async with client('config', token=identity.access_token) as api:
                    updated = await api.post('/agent/update', json={
                        **parent,
                        'related_agent_ids': [child_a_id, child_b_id],
                        'duty_prompt': 'Delegate the user request to both related agents and combine their replies.',
                    })
                    assert_status(updated, 200)
                    relationship = await api.get(f'/agent/call_relationship/{parent_id}')
                assert_status(relationship, 200)
                if str(child_a_id) not in relationship.text or str(child_b_id) not in relationship.text:
                    raise AssetDependencyError('agents', 'nested_id', detail='Owned child relationship was not persisted')
                register_asset('agents', 'nested_id', parent_id, owner_case_id=owner)
                register_asset('agents', 'parallel_id', parent_id, owner_case_id=owner)
                return parent_id


@asynccontextmanager
async def _draft_agent(
    identity,
    *,
    name_prefix: str = "d3-agent",
    retain_for_batch: bool = False,
    owner_case_id: str = "",
    registry_role: str = "",
    enabled_tool_ids: list[int] | None = None,
    allow_chat_metadata: bool | None = None,
    cleanup_identity: str = "tenant_a_user",
    model_ids: list[int] | None = None,
):
    if retain_for_batch and (not owner_case_id or not registry_role):
        raise RuntimeError("retained Agent requires owner_case_id and registry_role")
    unique = f"{name_prefix}-{uuid.uuid4().hex[:8]}"
    payload = {
        "name": unique.replace("-", "_"),
        "display_name": unique,
        "description": "D3 isolated Agent",
        "business_description": "Validate the configured D3 scenario",
        "max_steps": 5,
        "provide_run_summary": False,
        # Persist the model selected from config/models.yaml so runtime cases
        # exercise the configured provider rather than SDK environment fallbacks.
        "model_ids": model_ids if model_ids is not None else [await _llm_id(identity)],
        "enabled_tool_ids": enabled_tool_ids or [],
        "enabled_skill_ids": [],
        "enabled": True,
        "version_no": 0,
        "allow_chat_metadata": registry_role == "mcp" if allow_chat_metadata is None else allow_chat_metadata,
        "is_a2a": retain_for_batch and registry_role == "basic",
    }
    async with client("config", token=identity.access_token) as api:
        updated = await api.post("/agent/update", json=payload)
    assert_status(updated, 200)
    agent_id = int(updated.json()["agent_id"])
    # All subsequent round trips must target this exact draft. Without its ID,
    # callers spreading this payload into /agent/update can create a new Agent.
    payload['agent_id'] = agent_id
    if not retain_for_batch:
        try:
            register_asset('owned_agents',str(agent_id),agent_id,owner_case_id='DRAFT-FACTORY',
                cleanup={'service':'config','identity':identity.id,'method':'DELETE','path':'/agent',
                         'json':{'agent_id':agent_id},'allowed_statuses':[200,404]})
        except Exception:
            await _delete_draft(identity,agent_id)
            raise
    # Register before clear_new/publish: either later step may fail after the
    # product has already persisted the Agent.
    if retain_for_batch:
        register_asset("agents",f"{registry_role}_id",agent_id,owner_case_id=owner_case_id,
            cleanup={'service':'config','identity':cleanup_identity,'method':'DELETE','path':'/agent',
                     'json':{'agent_id':agent_id},'allowed_statuses':[200,404]})
    # Clear the new marker before another factory call so parent and child
    # Agents receive distinct IDs and the saved Agent becomes listable.
    try:
        async with client("config", token=identity.access_token) as api:
            released = await api.put(f"/agent/clear_new/{agent_id}")
        assert_status(released, 200)
    except BaseException:
        if not retain_for_batch:
            await _delete_draft(identity,agent_id)
        raise
    if retain_for_batch and registry_role == "basic":
        # Northbound APIs expose published versions only.  The same verified
        # Agent remains available to direct runtime tests through its draft.
        async with client("config", token=identity.access_token) as api:
            published = await api.post(
                f"/agent/{agent_id}/publish",
                json={"version_name": "daily-baseline", "release_note": "batch test asset"},
            )
        assert_status(published, 200)
        published_body = published.json()
        a2a_agent = published_body.get("a2a_agent") or {}
        endpoint_id = str(a2a_agent.get("endpoint_id") or "").strip()
        if endpoint_id:
            # Publishing is the real product operation that creates the local
            # A2A registration.  Keep its generated IDs batch-scoped instead
            # of requiring long-lived IDs in test-assets.yaml.
            async with client("config", token=identity.access_token) as api:
                enabled_a2a = await api.post(
                    f"/a2a/management/agents/{agent_id}/enable", json={},
                )
            assert_status(enabled_a2a, 200)
            register_asset(
                "agents", "local_a2a_id", agent_id, owner_case_id=owner_case_id,
            )
            register_asset(
                "a2a", "local_endpoint_id", endpoint_id, owner_case_id=owner_case_id,
            )
    if retain_for_batch:
        register_asset(
            "agents", f"{registry_role}_name", payload["name"], owner_case_id=owner_case_id,
        )
        if registry_role == "basic":
            # These roles exercise request/runtime behaviour rather than a
            # different persisted Agent topology, so the verified basic Agent
            # is the correct reusable producer asset.
            for alias in ("metadata_id", "attachment_id", "plan_id"):
                register_asset("agents", alias, agent_id, owner_case_id=owner_case_id)
            register_asset(
                "security", "prompt_injection_agent_id", agent_id,
                owner_case_id=owner_case_id,
            )
    primary = None
    try:
        yield agent_id, payload
    except BaseException as exc:
        primary = exc
        raise
    finally:
        if not retain_for_batch:
            try:
                await _delete_draft(identity,agent_id)
            except Exception as exc:
                try:
                    mark_asset_state('owned_agents',str(agent_id),'ORPHANED',detail=type(exc).__name__)
                except Exception:
                    pass  # Preserve the primary failure even if the journal is unavailable.
                if primary is None:
                    raise
                note = 'Owned draft cleanup failed; see asset journal'
                if hasattr(primary,'add_note'):
                    primary.add_note(note)
                else:
                    primary.__notes__ = [*getattr(primary,'__notes__',[]),note]

"""Create an owned automation task without executing the AGT-054 test."""
from datetime import datetime, timedelta, timezone
from .agent import _draft_agent
from .conversation import _create_conversation
from d3.assets import model_id
from shared.asset_registry import register_asset
from shared.http import client, assert_status, MODEL_TIMEOUT


async def prepare_automation_task(identity):
    owner='LOCAL-AUTOMATION-PREP'
    async with _draft_agent(identity, name_prefix='local-scheduler', retain_for_batch=True,
                            owner_case_id=owner, registry_role='automation_seed') as (agent_id, _):
        conversation_id=await _create_conversation(identity,'Local automation fixture')
        register_asset('automation','conversation_id',conversation_id,owner_case_id=owner,cleanup={
            'service':'runtime','identity':'tenant_a_user','method':'DELETE',
            'path':f'/conversation/{conversation_id}','allowed_statuses':[200,404]})
        async with client('runtime',token=identity.access_token,timeout=MODEL_TIMEOUT) as api:
            proposed=await api.post('/agent/automations/proposals',json={
                'conversation_id':conversation_id,'agent_id':agent_id,
                'message':'Tomorrow at 03:00 reply only LOCAL_AUTOMATION_OK. No tools or external resources.',
                'timezone':'UTC','model_id':await model_id('llm',identity)})
            assert_status(proposed,200)
            proposal_id=(proposed.json().get('data') or {})['proposal_id']
            # Enforce a future schedule before confirmation: do not rely on
            # model-generated dates, or allow the fixture to fire during setup.
            scheduled=await api.patch(f'/agent/automations/proposals/{proposal_id}',json={
                'schedule_trigger':{'mode':'ONCE','rule_type':'AT','timezone':'UTC',
                                    'start_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}})
            assert_status(scheduled,200)
            confirmed=await api.post(f'/agent/automations/proposals/{proposal_id}/confirm',json={})
            assert_status(confirmed,200)
            task_id=int((confirmed.json().get('data') or {})['task_id'])
            register_asset('automation','seeded_task_id',task_id,owner_case_id=owner,cleanup={
                'service':'runtime','identity':'tenant_a_user','method':'DELETE',
                'path':f'/agent/automations/{task_id}','allowed_statuses':[200,404]})
            paused=await api.post(f'/agent/automations/{task_id}/pause')
            assert_status(paused,200)
            detail=await api.get(f'/agent/automations/{task_id}')
            assert_status(detail,200)
            assert int((detail.json().get('data') or {})['task_id'])==task_id
        register_asset('reliability','scheduler_task_id',task_id,owner_case_id=owner)
        return task_id

"""Isolated share fixtures: real uploaded file, two distinct share scopes.

Only message seeding uses the product DB helper, because no public API exposes
message insertion without running an Agent. Share creation and reads use HTTP.
"""
import sys
from urllib.parse import quote
from .conversation import _create_conversation
from .files import _upload_attachment
from shared.asset_registry import register_asset
from shared.config import repo_root
from shared.postgres import apply_product_postgres_env
from shared.http import client, assert_status


def product_db():
    apply_product_postgres_env()
    for directory in (repo_root()/'backend', repo_root()/'sdk'):
        if str(directory) not in sys.path: sys.path.insert(0,str(directory))


def revoke_owned_share(token, identity):
    product_db()
    from database.conversation_share_db import revoke_conversation_share
    from database.client import as_dict, get_db_session
    from database.db_models import ConversationShare
    from sqlalchemy import select
    # Ownership validation must not depend on the public expiry filter. A share
    # may already be expired (or have a timezone incompatible with that filter).
    with get_db_session() as session:
        record=session.execute(select(ConversationShare).where(ConversationShare.share_token==token)).scalar_one_or_none()
        row=as_dict(record) if record is not None else None
    if row is None: return
    if str(row.get('created_by'))!=str(identity.user_id) or str(row.get('tenant_id'))!=str(identity.tenant_id):
        raise RuntimeError('share cleanup ownership mismatch')
    if row.get('status')=='revoked' or row.get('delete_flag')=='Y': return
    if not revoke_conversation_share(token,identity.user_id):
        raise RuntimeError('share revoke failed')


async def prepare_share_assets(identity):
    owner='LOCAL-SHARE-PREP'
    object_name=await _upload_attachment(identity)
    register_asset('files','share_attachment',object_name,owner_case_id=owner,cleanup={
        'service':'config','identity':identity.id,'method':'DELETE',
        'path':f'/file/storage/{quote(object_name,safe="/")}','allowed_statuses':[200,404]})
    product_db()
    from database.conversation_db import create_conversation_message
    scopes=[]
    for role in ('bound','other'):
        conversation=await _create_conversation(identity,'Isolated share '+role)
        register_asset('conversations','share_'+role,conversation,owner_case_id=owner,cleanup={
            'service':'runtime','identity':identity.id,'method':'DELETE',
            'path':f'/conversation/{conversation}','allowed_statuses':[200,404]})
        create_conversation_message({'conversation_id':conversation,'message_idx':0,'role':'user',
            'content':'Isolated share fixture', 'minio_files':[{'object_name':object_name,
            'name':'share-fixture.txt','content_type':'text/plain'}]},identity.user_id)
        async with client('runtime',token=identity.access_token) as api:
            # These cases exercise asset scope, not expiration. Explicit owner
            # cleanup provides the lifetime without relying on expiry semantics.
            shared=await api.post(f'/share/conversation/{conversation}',json={'mode':'all',
                'render_version':'legacy'})
        assert_status(shared,200)
        token=str(shared.json()['data']['share_id'])
        register_asset('sharing',role+'_token',token,owner_case_id=owner,sensitive=True,cleanup={
            'kind':'revoke_owned_share','identity':identity.id,'share_token':token})
        async with client('runtime') as public:
            snapshot=await public.get(f'/share/{token}')
        assert_status(snapshot,200)
        messages=snapshot.json()['data']['snapshot']['message']
        assets=[a['asset_id'] for message in messages for a in message.get('minio_files',[]) if 'asset_id' in a]
        if len(assets)!=1: raise AssertionError('share fixture must contain exactly one attachment')
        scopes.append((token,assets[0]))
    if scopes[0][1]==scopes[1][1]: raise AssertionError('different share scopes must have different asset IDs')
    register_asset('sharing','share_token',scopes[0][0],owner_case_id=owner,sensitive=True)
    register_asset('sharing','asset_id',scopes[0][1],owner_case_id=owner)
    register_asset('sharing','unbound_asset_id',scopes[1][1],owner_case_id=owner)

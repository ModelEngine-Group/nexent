"""Own the Agent and every tag row created by a single tag contract test."""
from contextlib import asynccontextmanager
import re
from shared.http import client
from shared.asset_registry import mark_asset_state
from .agent import _draft_agent
from .tags import register_tag_definition
from .ownership import register_owned_http


@asynccontextmanager
async def tag_contract_client(identity):
    owned=[]
    primary=None
    async with _draft_agent(identity,name_prefix='tag-contract') as (agent_id,_), \
            client('config',token=identity.access_token) as api:
        class Proxy:
            owned_agent_id=agent_id
            def __getattr__(self,name):return getattr(api,name)
            async def post(self,path,**kwargs):
                response=await api.post(path,**kwargs)
                if 200<=response.status_code<300:
                    definition=re.fullmatch(r'/tag-libraries/(\d+)/definitions',path)
                    value=re.fullmatch(r'/tag-libraries/(\d+)/definitions/(\d+)/values',path)
                    if definition:
                        body=response.json()
                        did=body['definition_id']
                        base=f'/tag-libraries/{definition[1]}/definitions/{did}'
                        owned.append(('tag_definitions',str(did),base))
                        for row in body.get('values',[]):
                            vid=row['value_id']
                            owned.append(('tag_values',str(vid),f'{base}/values/{vid}'))
                        register_tag_definition(identity,definition[1],body)
                    elif value:
                        vid=response.json()['value_id']
                        target=f'{path}/{vid}'
                        owned.append(('tag_values',str(vid),target))
                        register_owned_http(identity,'tag_values',vid,target)
                return response
        try:
            yield Proxy()
        except BaseException as exc:
            primary=exc
            raise
        finally:
            failures=[]
            # Assignment-conflict helper removes assignments in its finally;
            # no historical resources are included in this cleanup list.
            for section,key,path in sorted(set(owned),key=lambda row:row[0]!='tag_values'):
                try:
                    response=await api.delete(path)
                    if response.status_code not in (200,404):
                        raise RuntimeError('Owned tag cleanup rejected')
                    mark_asset_state(section,key,'DELETED')
                except Exception as exc:
                    failures.append(type(exc).__name__)
                    try:
                        mark_asset_state(section,key,'ORPHANED',detail=type(exc).__name__)
                    except Exception:
                        failures.append('RegistryWriteError')
            if failures and primary is None:
                raise RuntimeError('Owned tag cleanup failed; see asset journal')
            if failures and primary is not None:
                primary.__notes__=[*getattr(primary,'__notes__',[]),'Owned tag cleanup failed; see asset journal']

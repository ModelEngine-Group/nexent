"""Scoped provider CRUD client: persist ownership before caller assertions."""
from contextlib import asynccontextmanager
from shared.http import client
from shared.asset_registry import register_asset, mark_asset_state


@asynccontextmanager
async def owned_provider_client(identity):
    owned = []
    primary = None
    async with client('config', token=identity.access_token) as api:
        class Proxy:
            def __getattr__(self, name):
                return getattr(api, name)

            async def post(self, path, **kwargs):
                response = await api.post(path, **kwargs)
                if path == '/memory/providers' and 200 <= response.status_code < 300:
                    body = response.json()
                    pid = body.get('provider_config_id')
                    if pid is None:
                        raise RuntimeError('Successful provider creation omitted ownership ID')
                    pid = int(pid)
                    if pid not in owned:
                        owned.append(pid)
                    register_asset('owned_providers',str(pid),pid,
                        owner_case_id='PROVIDER-FACTORY',cleanup={
                            'service':'config','identity':identity.id,'method':'DELETE',
                            'path':f'/memory/providers/{pid}','allowed_statuses':[200,404]})
                return response

        try:
            yield Proxy()
        except BaseException as exc:
            primary = exc
            raise
        finally:
            failures = []
            for pid in reversed(owned):
                try:
                    response = await api.delete(f'/memory/providers/{pid}')
                    if response.status_code not in (200,404):
                        raise RuntimeError(f'Provider cleanup HTTP {response.status_code}')
                    mark_asset_state('owned_providers',str(pid),'DELETED')
                except Exception as exc:
                    failures.append(type(exc).__name__)
                    try:
                        mark_asset_state('owned_providers',str(pid),'ORPHANED',detail=type(exc).__name__)
                    except Exception:
                        failures.append('RegistryWriteError')
            if failures:
                if primary is None:
                    raise RuntimeError('Owned provider cleanup failed; see asset journal')
                note = 'Owned provider cleanup failed; see asset journal'
                if hasattr(primary,'add_note'):
                    primary.add_note(note)
                else:
                    primary.__notes__ = [*getattr(primary,'__notes__',[]),note]

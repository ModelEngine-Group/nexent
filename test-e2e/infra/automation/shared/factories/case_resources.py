"""Case-owned cleanup journals; no resource ownership inferred from prefixes."""
from contextlib import asynccontextmanager
import re

from shared.asset_registry import register_asset
from shared.http import client


def register_http(identity, case_id, section, key, path, *, method="DELETE", body=None):
    cleanup = {"service": "config", "identity": identity.id, "method": method,
               "path": path, "allowed_statuses": [200, 404]}
    if body is not None:
        cleanup["json"] = body
    register_asset(section, str(key), key, owner_case_id=case_id, cleanup=cleanup)


@asynccontextmanager
async def cleanup_case(case_id):
    """Finalize on assertion/setup failure; worker retries unresolved journal entries."""
    primary = None
    try:
        yield
    except BaseException as exc:
        primary = exc
        raise
    finally:
        from shared.asset_cleanup import cleanup_registered_assets
        try:
            outcomes = await cleanup_registered_assets(owner_case_ids={case_id})
            if any(row['result'] == 'ORPHANED' for row in outcomes):
                raise RuntimeError("Case resource cleanup incomplete; inspect asset journal")
        except Exception:
            if primary is None:
                raise
            primary.add_note("Case resource cleanup also failed; inspect asset journal")


class TagJournalClient:
    """Journal owned definitions; cleanup discovers their exact child values."""
    def __init__(self, api, identity, case_id):
        self.api, self.identity, self.case_id = api, identity, case_id

    def __getattr__(self, name):
        return getattr(self.api, name)

    async def post(self, path, **kwargs):
        response = await self.api.post(path, **kwargs)
        if response.status_code not in (200, 201):
            return response
        definition = re.fullmatch(r"/tag-libraries/(\d+)/definitions", path)
        if definition:
            row = response.json()
            did = row['definition_id']
            base = f"{path}/{did}"
            register_http(self.identity, self.case_id, 'tag_definitions', did, base)
        return response


@asynccontextmanager
async def owned_tag_client(identity, case_id):
    async with cleanup_case(case_id):
        async with client('config', token=identity.access_token) as api:
            yield TagJournalClient(api, identity, case_id)

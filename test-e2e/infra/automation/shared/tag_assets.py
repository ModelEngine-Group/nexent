"""Tag cleanup uses current-batch ownership, never historical name prefixes."""
from __future__ import annotations
from collections.abc import Iterable
import re
from shared.http import assert_status,client
from shared.asset_registry import all_registered_assets,mark_asset_state

AUTOMATION_DEFINITION_PREFIXES=('api_auto_','api-auto-','repo-tags-api-auto-')


def is_automation_definition(name: str,prefixes: Iterable[str]=AUTOMATION_DEFINITION_PREFIXES)->bool:
    """Naming classification only: this must never authorize deletion."""
    return any(name.strip().lower().startswith(prefix.lower()) for prefix in prefixes)


async def cleanup_automation_tag_definitions(token: str,*,owner_case_ids: set[str] | None=None)->list[int]:
    """Delete only journaled current-batch tag rows owned by tenant_a_admin.

    Do not scan user tools/Skills or clear their assignments. An in-use row is
    a cleanup failure, not permission to mutate its unknown consumers. Older
    batch cleanup requires its own ownership journal and separate invocation.
    """
    entries=[]
    for section,values in all_registered_assets().items():
        if not isinstance(values,dict):continue
        for key,entry in values.items():
            if not isinstance(entry,dict) or entry.get('source')!='dynamic' or entry.get('state')=='DELETED':continue
            if owner_case_ids is not None and entry.get('owner_case_id') not in owner_case_ids:continue
            cleanup=entry.get('cleanup') or {}
            path=str(cleanup.get('path') or '')
            match=re.fullmatch(r'/tag-libraries/(\d+)/definitions/(\d+)(?:/values/(\d+))?',path)
            if (not match or cleanup.get('identity')!='tenant_a_admin' or
                    cleanup.get('service')!='config' or cleanup.get('method')!='DELETE'):
                continue
            entries.append((section,key,path,match.group(2),match.group(3)))
    removed=[]
    failures=[]
    if not entries:return removed
    async with client('config',token=token) as api:
        for section,key,path,did,vid in sorted(entries,key=lambda row:row[4] is None):
            try:
                response=await api.delete(path)
                assert_status(response,(200,404))
                mark_asset_state(section,key,'DELETED')
                if vid is None:removed.append(int(did))
            except Exception as exc:
                failures.append(type(exc).__name__)
                mark_asset_state(section,key,'ORPHANED',detail=type(exc).__name__)
    if failures:
        raise RuntimeError('Owned tag cleanup failed; see current batch journal')
    return list(dict.fromkeys(removed))

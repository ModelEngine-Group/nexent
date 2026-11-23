"""Register a freshly created HTTP resource, never infer ownership from names."""
from shared.asset_registry import register_asset


def register_owned_http(identity, section, resource_id, path, *, statuses=(200,404)):
    return register_asset(section,str(resource_id),resource_id,owner_case_id='HTTP-ASSET-FACTORY',
        cleanup={'service':'config','identity':identity.id,'method':'DELETE',
                 'path':path,'allowed_statuses':list(statuses)})

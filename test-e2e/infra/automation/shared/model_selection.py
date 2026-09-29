"""Pure, strict configured-model resolution. No global config mutation."""
from shared.asset_registry import AssetDependencyError


def select_configured_model(config: dict, model_type: str, rows: list, *, selected_id=None) -> int:
    expected = [name.strip().casefold() for name in str(
        config.get('model') or config.get('model_name') or '').split(',') if name.strip()]
    def fail(reason):
        # No URLs, keys or response bodies in errors.
        raise AssetDependencyError('models', model_type, detail=reason)
    if not expected:
        fail('configured model/model_name is required; aliases are not provider model names')
    explicit = config.get('model_id')
    if explicit not in (None, ''):
        try:
            explicit = int(explicit)
        except (TypeError, ValueError):
            fail('configured model_id must be numeric')
    else:
        explicit = None
    candidates = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        actual_type = str(row.get('model_type') or row.get('type') or '').casefold()
        if actual_type != model_type.casefold():
            continue
        # display_name alone is not proof that the requested provider model is used.
        name = str(row.get('model_name') or row.get('name') or '').strip().casefold()
        try:
            numeric = int(row.get('model_id') or row.get('id'))
        except (TypeError, ValueError):
            continue
        if numeric > 0 and (explicit is None or numeric == explicit):
            candidates.append((name, numeric))
    for preferred in expected:
        ids = {numeric for name, numeric in candidates if name == preferred}
        if len(ids) == 1:
            return ids.pop()
        if len(ids) > 1:
            try:
                selected = int(selected_id)
            except (TypeError, ValueError):
                selected = None
            # Deployment selection only disambiguates candidates whose actual
            # name/type already match. It must not override configured order.
            if selected in ids:
                return selected
            fail('multiple matching configured models; set a verified tenant-local model_id')
    fail('no exact configured name/type/model_id match in the authenticated tenant')

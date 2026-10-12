from __future__ import annotations

import pytest

CASE_ID = 'API-AUTO-19E0779FED1B649A'

_ALWAYS_HIDDEN = ('knowledge_base_search', 'aidp_search')
_INDEPENDENT_AIDP = 'ind_aidp_search'
_ORDINARY_LOCAL_TOOL = 'read_file'


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D2')
def test_tool_list_is_user_selectable_deployment_control(monkeypatch):
    import services.tool_configuration_service as svc
    from consts import const

    selectable = svc._get_user_selectability

    for enabled in (False, True):
        monkeypatch.setattr(const, 'ENABLE_AIDP_KNOWLEDGE', enabled)
        for name in _ALWAYS_HIDDEN:
            assert selectable(name, True) is False
            assert selectable(name, False) is False

    for enabled in (False, True):
        monkeypatch.setattr(const, 'ENABLE_AIDP_KNOWLEDGE', enabled)
        assert selectable(_INDEPENDENT_AIDP, True) is True
        assert selectable(_INDEPENDENT_AIDP, False) is False
        # Validate the public serialized catalog, not just the private helper.
        by_name = {tool.name: tool for tool in svc.get_local_tools()}
        assert by_name[_INDEPENDENT_AIDP].is_user_selectable is True
        for name in _ALWAYS_HIDDEN:
            assert by_name[name].is_user_selectable is False
        assert all(isinstance(tool.model_dump()['is_user_selectable'], bool)
                   for tool in by_name.values())

    assert selectable(_ORDINARY_LOCAL_TOOL, True) is True
    assert selectable(_ORDINARY_LOCAL_TOOL, False) is False

    for name in (*_ALWAYS_HIDDEN, _INDEPENDENT_AIDP, _ORDINARY_LOCAL_TOOL):
        assert isinstance(selectable(name, True), bool)
        assert isinstance(selectable(name, False), bool)

    tools = svc.get_local_tools()
    assert tools
    by_name = {tool.name: tool for tool in tools}
    for tool in tools:
        assert isinstance(tool.name, str) and tool.name
        assert isinstance(tool.is_user_selectable, bool)

    for name in _ALWAYS_HIDDEN:
        assert name in by_name
        assert by_name[name].is_user_selectable is False

    assert _INDEPENDENT_AIDP in by_name
    assert by_name[_INDEPENDENT_AIDP].is_user_selectable is True

    assert _ORDINARY_LOCAL_TOOL in by_name
    assert by_name[_ORDINARY_LOCAL_TOOL].is_user_selectable is True

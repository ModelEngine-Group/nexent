from unittest.mock import MagicMock, patch

mock_linkup = MagicMock()

with patch.dict('sys.modules', {'linkup': mock_linkup}):
    from sdk.nexent.core.utils.observer import MessageObserver
    from sdk.nexent.core.tools.linkup_search_tool import LinkupSearchTool


def test_data_process_service_comes_from_parameter(monkeypatch):
    """The SDK must take data_process_service as a parameter, not read the environment"""
    monkeypatch.setenv("DATA_PROCESS_SERVICE", "http://from-env")
    observer = MagicMock(spec=MessageObserver)

    tool = LinkupSearchTool(linkup_api_key="k", observer=observer,
                            data_process_service="http://from-param")
    default_tool = LinkupSearchTool(linkup_api_key="k", observer=observer)

    assert tool.data_process_service == "http://from-param"
    assert default_tool.data_process_service is None

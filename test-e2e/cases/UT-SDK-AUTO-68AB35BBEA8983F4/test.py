import pytest
import json
import logging

from nexent.core.ext_components.aidp.aidp_search_tool import AidpSearchTool


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError('http status ' + str(self.status_code))

    def json(self):
        return self._payload


class _RecordingClient:
    def __init__(self):
        self.post_calls = []

    def post(self, url, headers=None, json=None, **kwargs):
        self.post_calls.append({
            'url': url,
            'headers': dict(headers or {}),
            'json': json,
        })
        return _FakeResponse(200, {'result': []})


SERVER_URL = 'https://aidp.example.com'
API_KEY = 'ak_test'
TENANT_ID = 'tenant1'
KDS_NAME_TO_ID = {'财务知识库': 'kb1', '人力知识库': 'kb2'}


def _make_tool():
    client = _RecordingClient()
    tool = AidpSearchTool(
        server_url=SERVER_URL,
        api_key=API_KEY,
        tenant_id=TENANT_ID,
        kds_list=json.dumps(['kb1', 'kb2']),
        kds_name_to_id_map=dict(KDS_NAME_TO_ID),
        observer=None,
    )
    tool._http_client = client
    return tool, client


@pytest.mark.case_id("UT-SDK-AUTO-68AB35BBEA8983F4")
@pytest.mark.stage('D1')
def test_aidp_search_tool_kds_whitelist_semantics(caplog):
    caplog.set_level(logging.INFO)

    tool, client = _make_tool()

    assert tool._whitelist_installed is False
    assert tool._allowed_kds_set == set()
    assert tool._filter_by_whitelist(['kb1', 'kb2']) == ['kb1', 'kb2']

    tool.set_allowed_kds(None)
    assert tool._whitelist_installed is False
    assert tool._allowed_kds_set == set()
    assert tool._filter_by_whitelist(['kb1', 'kb2']) == ['kb1', 'kb2']

    tool.set_allowed_kds([])
    assert tool._whitelist_installed is True
    assert tool._allowed_kds_set == set()
    assert tool._filter_by_whitelist(['kb1', 'kb2']) == []

    tool.set_allowed_kds(['kb1', 'kb3'])
    assert tool._whitelist_installed is True
    assert tool._filter_by_whitelist(['kb1', 'kb2', 'kb3']) == ['kb1', 'kb3']

    assert tool._convert_to_kds_ids(['财务知识库', 'kb2', '未知库']) == ['kb1', 'kb2', '未知库']
    assert tool._convert_to_kds_names(['kb1', 'kb2', 'kb9']) == ['财务知识库', '人力知识库', 'kb9']

    tool.set_allowed_kds([])
    empty_result = tool.forward('查询词', kds_list=['kb1', 'kb2'])
    assert client.post_calls == []
    parsed = json.loads(empty_result)
    assert parsed['results'] == []
    assert 'No accessible knowledge bases remained' in parsed['notice']

    tool.set_allowed_kds(['kb1'])
    nonempty_result = tool.forward('查询词', kds_list=['kb1', 'kb2'])
    assert len(client.post_calls) == 1
    posted = client.post_calls[0]
    assert posted['json']['kds_list'] == ['kb1']
    assert 'kb2' not in posted['json']['kds_list']

    assert API_KEY not in empty_result
    assert API_KEY not in nonempty_result
    assert API_KEY not in tool._build_retrieve_url()
    assert API_KEY not in caplog.text

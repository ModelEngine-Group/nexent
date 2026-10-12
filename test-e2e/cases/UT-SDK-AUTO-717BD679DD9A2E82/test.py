import json
import logging

import httpx
import pytest

import nexent.core.ext_components.aidp.aidp_search_tool as aidp_search_tool
from nexent.core.ext_components.aidp.aidp_search_tool import (
    AidpSearchError,
    AidpSearchTool,
)
from nexent.core.utils.observer import MessageObserver, ProcessType

BASE_URL = 'https://aidp.example.com'
TENANT_ID = 'tenant-placeholder'
API_KEY = 'ak_placeholder_token'
FULL_IMAGE_URL = (
    f'{BASE_URL}/KnowledgeBase/Tenants/{TENANT_ID}/KnowledgeBases/'
    'aidp-kb-1/data/img.png'
)
IMAGE_MARKER = '![AIDP image](/__aidp_image__/j1)'


class FakeResponse:
    def __init__(self, status_code, json_body=None):
        self.status_code = status_code
        self.reason_phrase = ''
        self._json_body = json_body
        self.request = None

    def json(self):
        return self._json_body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f'{self.status_code} {self.reason_phrase}',
                request=self.request,
                response=self,
            )


class FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, headers=None, json=None):
        self.calls.append({'url': url, 'headers': headers, 'json': json})
        return self._responses.pop(0)


def make_tool(monkeypatch, responses, observer=None, kds_list=None):
    if kds_list is None:
        kds_list = json.dumps(['kb-1'])
    tool = AidpSearchTool(
        server_url=BASE_URL,
        api_key=API_KEY,
        tenant_id=TENANT_ID,
        kds_list=kds_list,
        search_method='hybrid_search',
        observer=observer,
    )
    client = FakeClient(responses)
    tool._http_client = client
    sleeps = []
    monkeypatch.setattr(aidp_search_tool.time, 'sleep', lambda s: sleeps.append(s))
    return tool, client, sleeps


def collect_by_type(observer):
    by_type = {}
    for raw in observer.message_query:
        msg = json.loads(raw)
        by_type.setdefault(msg['type'], []).append(msg['content'])
    return by_type


def text_record(title, text, chunk_type='text', file_url='', score=0.9):
    return {
        'chunk_type': chunk_type,
        'file_url': file_url,
        'title': title,
        'text': text,
        'id': 'chunk-1',
        'score': score,
        'pages': [],
    }


@pytest.mark.stage('D1')
@pytest.mark.case_id('UT-SDK-AUTO-717BD679DD9A2E82')
def test_aidp_search_tool_retry_and_image_safety(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger='aidp_search_tool')

    observer = MessageObserver()
    ok_payload = {
        'result': [
            text_record('Doc One', 'first text', 'text', 'kb-1/file.txt'),
            text_record('Table One', 'table text', 'table', 'kb-1/table.csv', 0.8),
        ]
    }
    tool, client, sleeps = make_tool(
        monkeypatch, [FakeResponse(200, json_body=ok_payload)], observer
    )
    returned = tool.forward('hello', ['kb-1'])
    data = json.loads(returned)
    assert isinstance(data, dict)
    assert len(data['results']) == 2
    assert data['results'][0]['title'] == 'Doc One'
    assert data['results'][0]['text'] == 'first text'
    assert data['results'][0]['index'] == 'j1'
    assert data['results'][0]['reference_mark'] == '[[j1]]'
    assert data['results'][1]['index'] == 'j2'

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call['headers']['Authorization'] == f'Bearer {API_KEY}'
    assert call['json']['query'] == 'hello'
    assert call['json']['kds_list'] == ['kb-1']
    assert call['json']['search_method'] == 'hybrid_search'
    assert call['json']['multi_modal'] is True
    assert sleeps == []

    by_type = collect_by_type(observer)
    assert ProcessType.CARD.value in by_type
    card = json.loads(by_type[ProcessType.CARD.value][0])
    assert card == [{'icon': 'search', 'text': 'hello'}]
    assert ProcessType.SEARCH_CONTENT.value in by_type
    ui_items = json.loads(by_type[ProcessType.SEARCH_CONTENT.value][0])
    assert len(ui_items) == 2
    assert ProcessType.PICTURE_WEB.value not in by_type

    observer4 = MessageObserver()
    tool4, client4, sleeps4 = make_tool(
        monkeypatch,
        [FakeResponse(502), FakeResponse(503), FakeResponse(200, json_body=ok_payload)],
        observer4,
    )
    tool4.forward('retry-query', ['kb-1'])
    assert len(client4.calls) == 3
    for c in client4.calls:
        assert c['headers']['Authorization'] == f'Bearer {API_KEY}'
    assert sleeps4 == [0.5, 1.0]

    tool5, client5, _ = make_tool(
        monkeypatch, [FakeResponse(503), FakeResponse(503), FakeResponse(503)]
    )
    with pytest.raises(AidpSearchError) as exc503:
        tool5.forward('q', ['kb-1'])
    msg503 = str(exc503.value)
    assert 'HTTP 503' in msg503
    assert 'upload at least one document' in msg503
    assert 'httpx' not in msg503.lower()
    assert len(client5.calls) == 3

    for status in (502, 504):
        tool_x, client_x, _ = make_tool(
            monkeypatch, [FakeResponse(status), FakeResponse(status), FakeResponse(status)]
        )
        with pytest.raises(AidpSearchError) as exc_x:
            tool_x.forward('q', ['kb-1'])
        msg_x = str(exc_x.value)
        assert 'after 3 attempts' in msg_x
        assert 'httpx' not in msg_x.lower()
        assert len(client_x.calls) == 3

    observer6 = MessageObserver()
    image_payload = {
        'result': [
            text_record('Image Title', 'caption', 'image', 'aidp-kb-1/data/img.png', 0.9)
        ]
    }
    tool6, client6, _ = make_tool(
        monkeypatch, [FakeResponse(200, json_body=image_payload)], observer6
    )
    ret6 = tool6.forward('show image', ['kb-1'])
    assert FULL_IMAGE_URL not in ret6
    assert 'aidp-kb-1/data/img.png' not in ret6
    assert IMAGE_MARKER in ret6

    by_type6 = collect_by_type(observer6)
    assert ProcessType.PICTURE_WEB.value in by_type6
    picture6 = json.loads(by_type6[ProcessType.PICTURE_WEB.value][0])
    assert picture6['images_url'] == [FULL_IMAGE_URL]
    for content in by_type6[ProcessType.SEARCH_CONTENT.value]:
        assert FULL_IMAGE_URL not in content
    assert len(client6.calls) == 1

    observer7 = MessageObserver()
    html_payload = {
        'result': [
            text_record('Html Doc', 'before <img src=/md_image/foo.png alt=x> after')
        ]
    }
    tool7, client7, _ = make_tool(
        monkeypatch, [FakeResponse(200, json_body=html_payload)], observer7
    )
    ret7 = tool7.forward('q', ['kb-1'])
    model_text7 = json.loads(ret7)['results'][0]['text']
    assert '<img' not in model_text7
    assert 'before' in model_text7
    assert 'after' in model_text7
    ui_text7 = json.loads(collect_by_type(observer7)[ProcessType.SEARCH_CONTENT.value][0])[0]['text']
    assert '<img' not in ui_text7
    assert 'before' in ui_text7
    assert 'after' in ui_text7

    tool8, _, _ = make_tool(monkeypatch, [])
    with pytest.raises(ValueError):
        tool8.forward('', ['kb-1'])
    with pytest.raises(ValueError):
        tool8.forward('   ', ['kb-1'])

    with pytest.raises(ValueError):
        AidpSearchTool(
            server_url=BASE_URL,
            api_key=API_KEY,
            tenant_id=TENANT_ID,
            kds_list='{not json',
        )
    with pytest.raises(ValueError):
        AidpSearchTool(
            server_url=BASE_URL,
            api_key=API_KEY,
            tenant_id=TENANT_ID,
            kds_list=json.dumps([f'kb-{i}' for i in range(11)]),
        )

    tool401, client401, _ = make_tool(monkeypatch, [FakeResponse(401)])
    with pytest.raises(AidpSearchError):
        tool401.forward('q', ['kb-1'])
    assert len(client401.calls) == 1

    assert API_KEY not in caplog.text

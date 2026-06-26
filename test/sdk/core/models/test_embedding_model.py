import pytest
import requests
import sys
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from nexent.core.models.embedding_model import OpenAICompatibleEmbedding, JinaEmbedding, DashScopeMultimodalEmbedding

class DummyResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data or {"data": []}

    def raise_for_status(self):
        if not (200 <= self.status_code < 300):
            raise requests.HTTPError(f"Status {self.status_code}")

    def json(self):
        return self._json

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def openai_embedding_instance():
    """Return an OpenAICompatibleEmbedding instance with minimal viable attributes for tests."""

    return OpenAICompatibleEmbedding(
        model_name="dummy-model",
        base_url="https://api.example.com",
        api_key="dummy-key",
        embedding_dim=1536,
        ssl_verify=True,
    )


@pytest.fixture()
def jina_embedding_instance():
    """Return a JinaEmbedding instance with minimal viable attributes for tests."""

    return JinaEmbedding(api_key="dummy-key", ssl_verify=True)


def test_openai_embedding_default_model_type():
    emb = OpenAICompatibleEmbedding(
        model_name="dummy-model",
        base_url="https://api.example.com",
        api_key="dummy-key",
        embedding_dim=128,
        ssl_verify=True,
    )
    assert emb.model_type == "text"


def test_jina_embedding_default_model_type():
    emb = JinaEmbedding(api_key="dummy-key", ssl_verify=True)
    assert emb.model_type == "multimodal"


# ---------------------------------------------------------------------------
# Tests for dimension_check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dimension_check_success(openai_embedding_instance):
    """dimension_check should return embeddings when no exception is raised."""

    expected_embeddings = [[0.1, 0.2, 0.3]]

    with patch(
        "nexent.core.models.embedding_model.asyncio.to_thread",
        new_callable=AsyncMock,
        return_value=expected_embeddings,
    ) as mock_to_thread:
        result = await openai_embedding_instance.dimension_check()

        assert result == expected_embeddings
        mock_to_thread.assert_awaited_once()


@pytest.mark.asyncio
async def test_dimension_check_failure(openai_embedding_instance):
    """dimension_check should return an empty list when an exception is raised inside to_thread."""

    with patch(
        "nexent.core.models.embedding_model.asyncio.to_thread",
        new_callable=AsyncMock,
        side_effect=Exception("connection error"),
    ) as mock_to_thread:
        result = await openai_embedding_instance.dimension_check()

        assert result == []
        mock_to_thread.assert_awaited_once()


@pytest.mark.asyncio
async def test_openai_dimension_check_timeout_returns_empty(openai_embedding_instance):
    """dimension_check should return [] when Timeout propagates through asyncio.to_thread."""
    async def raise_timeout(*args, **kwargs):
        raise requests.exceptions.Timeout()

    with patch(
        "nexent.core.models.embedding_model.asyncio.to_thread",
        side_effect=raise_timeout,
    ):
        result = await openai_embedding_instance.dimension_check(timeout=3.0)
        assert result == []


# ---------------------------------------------------------------------------
# Tests for JinaEmbedding.dimension_check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jina_dimension_check_success(jina_embedding_instance):
    """dimension_check should return embeddings when no exception is raised."""

    expected_embeddings = [[0.5, 0.4, 0.3]]

    with patch(
        "nexent.core.models.embedding_model.asyncio.to_thread",
        new_callable=AsyncMock,
        return_value=expected_embeddings,
    ) as mock_to_thread:
        result = await jina_embedding_instance.dimension_check()

        assert result == expected_embeddings
        mock_to_thread.assert_awaited_once()


@pytest.mark.asyncio
async def test_jina_dimension_check_failure(jina_embedding_instance):
    """dimension_check should return an empty list when an exception is raised inside to_thread."""

    with patch(
        "nexent.core.models.embedding_model.asyncio.to_thread",
        new_callable=AsyncMock,
        side_effect=Exception("connection error"),
    ) as mock_to_thread:
        result = await jina_embedding_instance.dimension_check()

        assert result == []
        mock_to_thread.assert_awaited_once()


@pytest.mark.asyncio
async def test_jina_dimension_check_timeout_returns_empty(jina_embedding_instance):
    """dimension_check should return [] when Timeout propagates through asyncio.to_thread."""
    async def raise_timeout(*args, **kwargs):
        raise requests.exceptions.Timeout()

    with patch(
        "nexent.core.models.embedding_model.asyncio.to_thread",
        side_effect=raise_timeout,
    ):
        result = await jina_embedding_instance.dimension_check(timeout=3.0)
        assert result == []


# ---------------------------------------------------------------------------
# Tests for OpenAICompatibleEmbedding.get_embeddings (retry, metadata, etc.)
# ---------------------------------------------------------------------------


def test_openai_get_embeddings_success_returns_list(openai_embedding_instance):
    """Should return list of embeddings when with_metadata is False."""

    fake_response = {"data": [{"embedding": [0.9, 0.8]}]}

    with patch(
        "nexent.core.models.embedding_model.OpenAICompatibleEmbedding._make_request",
        return_value=fake_response,
    ) as mock_make_request:
        result = openai_embedding_instance.get_embeddings(
            ["hello"], with_metadata=False, timeout=3
        )

        assert result == [[0.9, 0.8]]
        mock_make_request.assert_called_once()


def test_openai_get_embeddings_with_metadata(openai_embedding_instance):
    """Should return full response when with_metadata is True."""

    fake_response = {
        "data": [{"embedding": [1, 2, 3]}], "meta": {"foo": "bar"}}

    with patch(
        "nexent.core.models.embedding_model.OpenAICompatibleEmbedding._make_request",
        return_value=fake_response,
    ) as mock_make_request:
        result = openai_embedding_instance.get_embeddings(
            ["x"], with_metadata=True, timeout=1
        )

        assert result == fake_response
        mock_make_request.assert_called_once()


def test_openai_get_embeddings_timeout_retry_succeeds(openai_embedding_instance):
    """First call times out, second succeeds; timeouts increase linearly."""

    fake_response = {"data": [{"embedding": [0.1, 0.2]}]}

    def side_effect(data, timeout=None):
        # First attempt -> timeout, second attempt -> success
        calls = side_effect.calls
        side_effect.calls += 1
        if calls == 0:
            raise requests.exceptions.Timeout()
        return fake_response

    side_effect.calls = 0

    with patch(
        "nexent.core.models.embedding_model.OpenAICompatibleEmbedding._make_request",
        side_effect=side_effect,
    ) as mock_make_request:
        result = openai_embedding_instance.get_embeddings(
            ["a"], with_metadata=False, timeout=None, retries=2, retry_timeout_step=2
        )

        assert result == [[0.1, 0.2]]

        # Verify linear timeouts: 2 (first), 4 (second)
        timeouts = [
            call.kwargs.get("timeout") for call in mock_make_request.call_args_list
        ]
        assert timeouts == [2, 4]


def test_openai_get_embeddings_timeout_exhausts_raises(openai_embedding_instance):
    """Should raise Timeout after exhausting retries."""

    with patch(
        "nexent.core.models.embedding_model.OpenAICompatibleEmbedding._make_request",
        side_effect=requests.exceptions.Timeout(),
    ) as mock_make_request:
        with pytest.raises(requests.exceptions.Timeout):
            openai_embedding_instance.get_embeddings(
                ["a"],
                with_metadata=False,
                timeout=None,
                retries=2,
                retry_timeout_step=1,
            )

        # Called attempts = retries + 1 = 3; timeouts 1, 2, 3
        timeouts = [
            call.kwargs.get("timeout") for call in mock_make_request.call_args_list
        ]
        assert timeouts == [1, 2, 3]


# ---------------------------------------------------------------------------
# Tests for JinaEmbedding.get_embeddings delegation and retry
# ---------------------------------------------------------------------------


def test_jina_get_embeddings_converts_text_and_delegates(jina_embedding_instance):
    """String input should be converted to multimodal and delegated to get_multimodal_embeddings."""

    captured_inputs = {}

    def side_effect(inputs, with_metadata=False, timeout=None):
        captured_inputs["inputs"] = inputs
        return [[0.3, 0.4]]

    with patch(
        "nexent.core.models.embedding_model.JinaEmbedding.get_multimodal_embeddings",
        side_effect=side_effect,
    ) as mock_delegate:
        result = jina_embedding_instance.get_embeddings(
            "hello", with_metadata=False, timeout=5
        )

        assert result == [[0.3, 0.4]]
        assert captured_inputs["inputs"] == [{"text": "hello"}]
        mock_delegate.assert_called_once()


def test_jina_get_embeddings_timeout_retry_succeeds(jina_embedding_instance):
    """First call times out, second succeeds; timeouts increase linearly."""

    def side_effect(inputs, with_metadata=False, timeout=None):
        calls = side_effect.calls
        side_effect.calls += 1
        if calls == 0:
            raise requests.exceptions.Timeout()
        return [[1.0, 2.0, 3.0]]

    side_effect.calls = 0

    with patch(
        "nexent.core.models.embedding_model.JinaEmbedding.get_multimodal_embeddings",
        side_effect=side_effect,
    ) as mock_delegate:
        result = jina_embedding_instance.get_embeddings(
            ["hello"],
            with_metadata=False,
            timeout=None,
            retries=2,
            retry_timeout_step=2,
        )

        assert result == [[1.0, 2.0, 3.0]]
        # Verify timeouts 2, 4
        timeouts = [call.kwargs.get("timeout")
                    for call in mock_delegate.call_args_list]
        assert timeouts == [2, 4]


def test_jina_get_embeddings_timeout_exhausts_raises(jina_embedding_instance):
    """Should raise Timeout after exhausting retries."""

    with patch(
        "nexent.core.models.embedding_model.JinaEmbedding.get_multimodal_embeddings",
        side_effect=requests.exceptions.Timeout(),
    ) as mock_delegate:
        with pytest.raises(requests.exceptions.Timeout):
            jina_embedding_instance.get_embeddings(
                ["x"],
                with_metadata=False,
                timeout=None,
                retries=2,
                retry_timeout_step=1,
            )

        # Called 3 times with timeouts 1, 2, 3
        timeouts = [call.kwargs.get("timeout")
                    for call in mock_delegate.call_args_list]
        assert timeouts == [1, 2, 3]


def test_jina_get_multimodal_embeddings_parses_embeddings(jina_embedding_instance):
    """Should parse embeddings from response when with_metadata is False."""

    fake_response = {
        "data": [
            {"embedding": [0.11, 0.22]},
            {"embedding": [0.33, 0.44]},
        ]
    }

    mock_resp = Mock()
    mock_resp.raise_for_status = Mock()
    mock_resp.json = Mock(return_value=fake_response)

    with patch.object(jina_embedding_instance.session, "post", return_value=mock_resp) as mock_post:
        inputs = [{"text": "t1"}, {"image": "http://x/y.jpg"}]
        result = jina_embedding_instance.get_multimodal_embeddings(
            inputs, with_metadata=False, timeout=3
        )

        assert result == [[0.11, 0.22], [0.33, 0.44]]
        mock_post.assert_called_once()
        # Assert truncate flag is included in request payload
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"].get("truncate") is True


def test_jina_get_multimodal_embeddings_with_metadata(jina_embedding_instance):
    """Should return full response when with_metadata is True."""

    fake_response = {
        "data": [
            {"embedding": [9, 9, 9]},
        ],
        "meta": {"m": 1},
    }

    mock_resp = Mock()
    mock_resp.raise_for_status = Mock()
    mock_resp.json = Mock(return_value=fake_response)

    with patch.object(jina_embedding_instance.session, "post", return_value=mock_resp) as mock_post:
        inputs = [{"text": "t"}]
        result = jina_embedding_instance.get_multimodal_embeddings(
            inputs, with_metadata=True, timeout=4
        )
        # Validate response and truncate flag usage
        assert result == fake_response
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"].get("truncate") is True


def test_jina_get_multimodal_embeddings_timeout_retry_succeeds(jina_embedding_instance):
    """First call times out, second succeeds; timeouts increase linearly."""

    fake_response = {
        "data": [
            {"embedding": [0.5, 0.6]},
        ]
    }

    captured_jsons = []

    def side_effect(url, headers=None, json=None, timeout=None, **kwargs):
        calls = side_effect.calls
        side_effect.calls += 1
        if calls == 0:
            raise requests.exceptions.Timeout()
        captured_jsons.append(json)
        mock_resp = Mock()
        mock_resp.raise_for_status = Mock()
        mock_resp.json = Mock(return_value=fake_response)
        return mock_resp

    side_effect.calls = 0

    with patch.object(jina_embedding_instance.session, "post", side_effect=side_effect) as mock_post:
        inputs = [{"text": "t"}]
        result = jina_embedding_instance.get_multimodal_embeddings(
            inputs, with_metadata=False, timeout=None, retries=2, retry_timeout_step=2
        )

        assert result == [[0.5, 0.6]]
        timeouts = [call.kwargs.get("timeout")
                    for call in mock_post.call_args_list]
        assert timeouts == [2, 4]
        # Ensure truncate flag present in at least one request body
        assert any(j.get("truncate") is True for j in captured_jsons)


def test_jina_get_multimodal_embeddings_timeout_exhausts_raises(
    jina_embedding_instance,
):
    """Should raise Timeout after exhausting retries."""

    with patch.object(
        jina_embedding_instance.session,
        "post",
        side_effect=requests.exceptions.Timeout(),
    ) as mock_post:
        with pytest.raises(requests.exceptions.Timeout):
            jina_embedding_instance.get_multimodal_embeddings(
                [{"text": "t"}],
                with_metadata=False,
                timeout=None,
                retries=2,
                retry_timeout_step=1,
            )

        timeouts = [call.kwargs.get("timeout")
                    for call in mock_post.call_args_list]
        assert timeouts == [1, 2, 3]


# ---------------------------------------------------------------------------
# Additional coverage for tail-return and ConnectionError branches
# ---------------------------------------------------------------------------


def test_jina_get_embeddings_returns_empty_when_attempts_skipped(jina_embedding_instance):
    """When retries < 0, loop is skipped and returns []."""

    result = jina_embedding_instance.get_embeddings(
        "x", with_metadata=False, timeout=None, retries=-1
    )

    assert result == []


def test_jina_get_multimodal_embeddings_returns_empty_when_attempts_skipped(jina_embedding_instance):
    """When retries < 0, loop is skipped and returns []."""

    result = jina_embedding_instance.get_multimodal_embeddings(
        [{"text": "x"}], with_metadata=False, timeout=None, retries=-1
    )

    assert result == []


@pytest.mark.asyncio
async def test_jina_dimension_check_connection_error_returns_empty(jina_embedding_instance):
    """dimension_check should return [] on ConnectionError."""

    with patch(
        "nexent.core.models.embedding_model.asyncio.to_thread",
        new_callable=AsyncMock,
        side_effect=requests.exceptions.ConnectionError(),
    ):
        result = await jina_embedding_instance.dimension_check()

        assert result == []


def test_openai_get_embeddings_string_prepares_input_list(openai_embedding_instance):
    """String input should be wrapped into a one-element list in request payload."""

    captured = {}

    def side_effect(data, timeout=None):
        captured["input"] = data["input"]
        return {"data": [{"embedding": [0.21, 0.22]}]}

    with patch(
        "nexent.core.models.embedding_model.OpenAICompatibleEmbedding._make_request",
        side_effect=side_effect,
    ) as mock_make_request:
        result = openai_embedding_instance.get_embeddings(
            "hello-openai", with_metadata=False, timeout=3
        )

        assert captured["input"] == ["hello-openai"]
        assert result == [[0.21, 0.22]]
        mock_make_request.assert_called_once()


def test_openai_make_request_invokes_requests_post(openai_embedding_instance):
    """Cover OpenAI _make_request by patching session.post path."""

    fake_response = {"data": [{"embedding": [7, 8]}]}

    mock_resp = Mock()
    mock_resp.raise_for_status = Mock()
    mock_resp.json = Mock(return_value=fake_response)

    with patch.object(openai_embedding_instance.session, "post", return_value=mock_resp) as mock_post:
        result = openai_embedding_instance.get_embeddings(
            ["hi"], with_metadata=False, timeout=2
        )

        assert result == [[7, 8]]
        mock_post.assert_called_once()


def test_openai_get_embeddings_returns_empty_when_attempts_skipped(openai_embedding_instance):
    """When retries < 0, loop is skipped and returns []."""

    result = openai_embedding_instance.get_embeddings(
        ["x"], with_metadata=False, timeout=None, retries=-1
    )

    assert result == []


@pytest.mark.asyncio
async def test_openai_dimension_check_connection_error_returns_empty(openai_embedding_instance):
    """dimension_check should return [] on ConnectionError."""

    with patch(
        "nexent.core.models.embedding_model.asyncio.to_thread",
        new_callable=AsyncMock,
        side_effect=requests.exceptions.ConnectionError(),
    ):
        result = await openai_embedding_instance.dimension_check()

        assert result == []

def test_api_key_normalization_and_verify_jina(monkeypatch):
    captured = {}

    def fake_post(self, url, headers=None, json=None, timeout=None, verify=True, **kwargs):
        captured['url'] = url
        captured['headers'] = headers
        captured['verify'] = verify
        return DummyResponse()

    monkeypatch.setattr("requests.Session.post", fake_post)

    # api_key containing Bearer prefix should be normalized
    emb = JinaEmbedding(api_key="my-secret", base_url="https://example.com/emb", ssl_verify=False)
    data = emb._prepare_multimodal_input([{"text": "hello"}])
    resp = emb._make_request(data, timeout=1)
    assert captured['headers']["Authorization"].startswith("Bearer ")
    # verify should be passed through
    assert captured['verify'] is False


def test_api_key_normalization_and_verify_openaicompatible(monkeypatch):
    captured = {}

    def fake_post(self, url, headers=None, json=None, timeout=None, verify=True, **kwargs):
        captured['url'] = url
        captured['headers'] = headers
        captured['verify'] = verify
        return DummyResponse()

    monkeypatch.setattr("requests.Session.post", fake_post)

    emb = OpenAICompatibleEmbedding(model_name="m", base_url="https://api.example/emb", api_key="KEY", embedding_dim=16, ssl_verify=True)
    data = emb._prepare_input("hi")
    resp = emb._make_request(data, timeout=1)
    assert captured['headers']["Authorization"].count("Bearer") == 1
    assert captured['verify'] is True


def test_textembedding_super_init_executes():
    """Create a concrete subclass of TextEmbedding that calls super().__init__
    to execute the `super().__init__(model_name, base_url, api_key, embedding_dim, ssl_verify=ssl_verify)` line.
    """
    # Use the dynamically-loaded module alias from earlier in this file
    TextEmbedding = OpenAICompatibleEmbedding.__mro__[1]  # TextEmbedding class (parent of OpenAICompatibleEmbedding)

    class ConcreteTextEmbedding(TextEmbedding):  # type: ignore[misc]
        def __init__(self, *args, **kwargs):
            # This will call TextEmbedding.__init__, which in turn calls BaseEmbedding.__init__
            super().__init__(*args, **kwargs)

        def get_embeddings(self, *args, **kwargs):
            return []

        async def dimension_check(self, timeout: float = 5.0):
            return []

    # Instantiation should succeed and therefore the super().__init__ line was executed
    inst = ConcreteTextEmbedding(model_name="m", base_url="u", api_key="k", embedding_dim=16, ssl_verify=False)
    assert inst is not None
    # Also assert that it's an instance of TextEmbedding for clarity
    assert isinstance(inst, TextEmbedding)


def test_jina_make_request_raises_http_error(monkeypatch):
    """Ensure _make_request propagates HTTP errors from requests.post"""

    def fake_post(self, url, headers=None, json=None, timeout=None, verify=True, **kwargs):
        class BadResp:
            status_code = 500

            def raise_for_status(self):
                raise requests.HTTPError("Server error")

        return BadResp()

    monkeypatch.setattr("requests.Session.post", fake_post)

    emb = JinaEmbedding(api_key="k", base_url="https://api.jina.ai/v1/embeddings", ssl_verify=True)
    data = emb._prepare_multimodal_input([{"text": "hi"}])
    with pytest.raises(requests.HTTPError):
        emb._make_request(data, timeout=1)


def test_openai_make_request_raises_http_error(monkeypatch):
    """Ensure OpenAICompatibleEmbedding._make_request propagates HTTP errors"""

    def fake_post(self, url, headers=None, json=None, timeout=None, verify=True, **kwargs):
        class BadResp:
            status_code = 502

            def raise_for_status(self):
                raise requests.HTTPError("Bad Gateway")

        return BadResp()

    monkeypatch.setattr("requests.Session.post", fake_post)

    emb = OpenAICompatibleEmbedding(model_name="m", base_url="https://api.example.com/emb", api_key="k", embedding_dim=16, ssl_verify=False)
    data = emb._prepare_input("hello")
    with pytest.raises(requests.HTTPError):
        emb._make_request(data, timeout=2)


def test_jina_get_multimodal_embeddings_missing_data_key(monkeypatch):
    """If the response JSON lacks 'data', a KeyError should surface when with_metadata=False"""

    class RespNoData:
        def raise_for_status(self):
            pass

        def json(self):
            return {"meta": {"ok": True}}

    monkeypatch.setattr("requests.Session.post", lambda *a, **k: RespNoData())

    emb = JinaEmbedding(api_key="k")
    with pytest.raises(KeyError):
        emb.get_multimodal_embeddings([{"text": "t"}], with_metadata=False, timeout=1)


# ---------------------------------------------------------------------------
# Tests for record_model_call monitoring wrapper
# ---------------------------------------------------------------------------


def test_openai_get_embeddings_calls_record_model_call(mocker):
    """OpenAICompatibleEmbedding.get_embeddings calls record_model_call with correct args."""
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=None)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    mock_record = mocker.patch(
        "nexent.core.models.embedding_model.record_model_call",
        return_value=mock_ctx,
    )
    mock_resp = Mock()
    mock_resp.raise_for_status = Mock()
    mock_resp.json.return_value = {"data": [{"embedding": [0.1, 0.2]}]}

    emb = OpenAICompatibleEmbedding(
        model_name="text-emb-3",
        base_url="https://api.example.com",
        api_key="k",
        embedding_dim=2,
        ssl_verify=True,
    )
    mocker.patch.object(emb.session, "post", return_value=mock_resp)
    emb.get_embeddings(["hello"], with_metadata=False, timeout=5)

    mock_record.assert_called_once_with(
        "embedding", "text-emb-3", display_name="text-emb-3"
    )


def test_jina_get_embeddings_calls_record_model_call(mocker):
    """JinaEmbedding.get_multimodal_embeddings calls record_model_call with correct args."""
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=None)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    mock_record = mocker.patch(
        "nexent.core.models.embedding_model.record_model_call",
        return_value=mock_ctx,
    )
    mock_resp = Mock()
    mock_resp.raise_for_status = Mock()
    mock_resp.json.return_value = {"data": [{"embedding": [0.1, 0.2]}]}

    emb = JinaEmbedding(api_key="k", ssl_verify=True)
    mocker.patch.object(emb.session, "post", return_value=mock_resp)
    emb.get_multimodal_embeddings([{"text": "hi"}], with_metadata=False, timeout=5)

    mock_record.assert_called_once_with(
        "multi_embedding", emb.model, display_name=emb.model
    )


# ---------------------------------------------------------------------------
# Tests for DashScopeMultimodalEmbedding
# ---------------------------------------------------------------------------


@pytest.fixture()
def dashscope_embedding_instance():
    """Return a DashScopeMultimodalEmbedding instance with minimal viable attributes."""
    return DashScopeMultimodalEmbedding(
        api_key="dummy-key",
        base_url="https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding",
        model_name="text-embedding-vision",
        embedding_dim=1024,
        ssl_verify=True,
    )


def test_dashscope_init_sets_attributes(dashscope_embedding_instance):
    """DashScopeMultimodalEmbedding.__init__ should set all attributes correctly."""
    emb = dashscope_embedding_instance
    assert emb.api_key == "dummy-key"
    assert emb.model == "text-embedding-vision"
    assert emb.embedding_dim == 1024
    assert emb.ssl_verify is True
    assert "Authorization" in emb.headers


def test_dashscope_prepare_multimodal_input_formats_correctly(dashscope_embedding_instance):
    """_prepare_multimodal_input should return DashScope-compatible format with 'contents' key."""
    inputs = [{"text": "hello"}, {"image": "http://x.jpg"}]
    result = dashscope_embedding_instance._prepare_multimodal_input(inputs)
    assert result["model"] == "text-embedding-vision"
    assert result["input"]["contents"] == inputs


def test_dashscope_get_embeddings_with_string_input(dashscope_embedding_instance):
    """String input should be wrapped as single-element dict list."""
    captured = {}

    def side_effect(data, timeout=None):
        captured["input"] = data["input"]
        return {"output": {"embeddings": [{"embedding": [0.1, 0.2]}]}}

    with patch.object(
        dashscope_embedding_instance, "_make_request", side_effect=side_effect
    ):
        result = dashscope_embedding_instance.get_embeddings(
            "hello", with_metadata=False, timeout=3
        )
        assert captured["input"]["contents"] == [{"text": "hello"}]
        assert result == [[0.1, 0.2]]


def test_dashscope_get_embeddings_with_list_input(dashscope_embedding_instance):
    """List input should be converted to multimodal dicts."""
    captured = {}

    def side_effect(data, timeout=None):
        captured["input"] = data["input"]
        return {"output": {"embeddings": [{"embedding": [0.3, 0.4]}]}}

    with patch.object(
        dashscope_embedding_instance, "_make_request", side_effect=side_effect
    ):
        result = dashscope_embedding_instance.get_embeddings(
            ["a", "b"], with_metadata=False, timeout=3
        )
        assert captured["input"]["contents"] == [{"text": "a"}, {"text": "b"}]
        assert result == [[0.3, 0.4]]


def test_dashscope_get_embeddings_with_metadata(dashscope_embedding_instance):
    """with_metadata=True should return the raw response dict."""
    fake_response = {"output": {"embeddings": [{"embedding": [1.0]}]}, "usage": {"total": 1}}

    with patch.object(
        dashscope_embedding_instance, "_make_request", return_value=fake_response
    ):
        result = dashscope_embedding_instance.get_embeddings(
            ["x"], with_metadata=True, timeout=1
        )
        assert result == fake_response


def test_dashscope_get_embeddings_timeout_retry_succeeds(dashscope_embedding_instance):
    """First call times out, second succeeds with linear timeout growth."""
    fake_response = {"output": {"embeddings": [{"embedding": [0.9]}]}}

    def side_effect(data, timeout=None):
        calls = side_effect.calls
        side_effect.calls += 1
        if calls == 0:
            raise requests.exceptions.Timeout()
        return fake_response

    side_effect.calls = 0

    with patch.object(
        dashscope_embedding_instance, "_make_request", side_effect=side_effect
    ):
        result = dashscope_embedding_instance.get_embeddings(
            ["a"], with_metadata=False, timeout=None, retries=2, retry_timeout_step=2
        )
        assert result == [[0.9]]
        timeouts = [call.kwargs.get("timeout")
                    for call in dashscope_embedding_instance._make_request.call_args_list]
        assert timeouts == [2, 4]


def test_dashscope_get_embeddings_timeout_exhausts_raises(dashscope_embedding_instance):
    """Should raise Timeout after exhausting retries."""
    with patch.object(
        dashscope_embedding_instance, "_make_request",
        side_effect=requests.exceptions.Timeout(),
    ):
        with pytest.raises(requests.exceptions.Timeout):
            dashscope_embedding_instance.get_embeddings(
                ["x"], with_metadata=False, timeout=None, retries=2, retry_timeout_step=1
            )
        timeouts = [call.kwargs.get("timeout")
                    for call in dashscope_embedding_instance._make_request.call_args_list]
        assert timeouts == [1, 2, 3]


def test_dashscope_get_embeddings_returns_empty_when_attempts_skipped(dashscope_embedding_instance):
    """When retries < 0, the loop is skipped and returns []."""
    result = dashscope_embedding_instance.get_embeddings(
        ["x"], with_metadata=False, timeout=None, retries=-1
    )
    assert result == []


def test_dashscope_get_embeddings_calls_record_model_call(mocker):
    """get_embeddings should call record_model_call."""
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=None)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    mock_record = mocker.patch(
        "nexent.core.models.embedding_model.record_model_call",
        return_value=mock_ctx,
    )
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "output": {"embeddings": [{"embedding": [0.1, 0.2]}]}
    }

    emb = DashScopeMultimodalEmbedding(
        api_key="k",
        base_url="https://dashscope.example.com",
        model_name="text-embedding-vision",
        embedding_dim=2,
        ssl_verify=True,
    )
    mocker.patch.object(emb.session, "post", return_value=mock_resp)
    emb.get_embeddings(["hello"], with_metadata=False, timeout=5)

    mock_record.assert_called_once_with(
        "multi_embedding", "text-embedding-vision", display_name="text-embedding-vision"
    )


@pytest.mark.asyncio
async def test_dashscope_dimension_check_connection_error_returns_empty(mocker):
    """dimension_check should return [] on ConnectionError."""
    emb = DashScopeMultimodalEmbedding(
        api_key="k",
        base_url="https://dashscope.example.com",
        model_name="text-embedding-vision",
        embedding_dim=1024,
        ssl_verify=True,
    )
    mocker.patch.object(
        emb, "get_multimodal_embeddings",
        side_effect=requests.exceptions.ConnectionError(),
    )
    result = await emb.dimension_check(timeout=5.0)
    assert result == []


@pytest.mark.asyncio
async def test_dashscope_dimension_check_timeout_returns_empty(mocker):
    """dimension_check should return [] on Timeout."""
    emb = DashScopeMultimodalEmbedding(
        api_key="k",
        base_url="https://dashscope.example.com",
        model_name="text-embedding-vision",
        embedding_dim=1024,
        ssl_verify=True,
    )
    mocker.patch.object(
        emb, "get_multimodal_embeddings",
        side_effect=requests.exceptions.Timeout(),
    )
    result = await emb.dimension_check(timeout=3.0)
    assert result == []


@pytest.mark.asyncio
async def test_dashscope_dimension_check_generic_exception_returns_empty(mocker):
    """dimension_check should return [] on generic Exception."""
    emb = DashScopeMultimodalEmbedding(
        api_key="k",
        base_url="https://dashscope.example.com",
        model_name="text-embedding-vision",
        embedding_dim=1024,
        ssl_verify=True,
    )
    mocker.patch.object(
        emb, "get_multimodal_embeddings",
        side_effect=RuntimeError("unexpected"),
    )
    result = await emb.dimension_check(timeout=5.0)
    assert result == []


@pytest.mark.asyncio
async def test_dashscope_dimension_check_success(mocker):
    """dimension_check should return embeddings on success."""
    emb = DashScopeMultimodalEmbedding(
        api_key="k",
        base_url="https://dashscope.example.com",
        model_name="text-embedding-vision",
        embedding_dim=1024,
        ssl_verify=True,
    )
    mocker.patch.object(
        emb, "get_multimodal_embeddings",
        return_value=[[0.1, 0.2, 0.3]],
    )
    result = await emb.dimension_check(timeout=5.0)
    assert result == [[0.1, 0.2, 0.3]]


# ---------------------------------------------------------------------------
# Additional coverage for exception branches and edge cases
# ---------------------------------------------------------------------------


def test_jina_get_embeddings_connection_error_propagates(jina_embedding_instance):
    """ConnectionError propagates (only Timeout is caught in get_embeddings)."""
    with patch.object(
        jina_embedding_instance.session,
        "post",
        side_effect=requests.exceptions.ConnectionError(),
    ):
        with pytest.raises(requests.exceptions.ConnectionError):
            jina_embedding_instance.get_embeddings(
                ["x"], with_metadata=False, timeout=5
            )


def test_jina_get_embeddings_generic_exception_propagates(jina_embedding_instance):
    """Generic Exception propagates (only Timeout is caught in get_embeddings)."""
    with patch.object(
        jina_embedding_instance.session,
        "post",
        side_effect=RuntimeError("unexpected"),
    ):
        with pytest.raises(RuntimeError):
            jina_embedding_instance.get_embeddings(
                ["x"], with_metadata=False, timeout=5
            )


def test_jina_get_multimodal_embeddings_connection_error_propagates(jina_embedding_instance):
    """ConnectionError propagates from get_multimodal_embeddings."""
    with patch.object(
        jina_embedding_instance.session,
        "post",
        side_effect=requests.exceptions.ConnectionError(),
    ):
        with pytest.raises(requests.exceptions.ConnectionError):
            jina_embedding_instance.get_multimodal_embeddings(
                [{"text": "x"}], with_metadata=False, timeout=5
            )


def test_jina_get_multimodal_embeddings_generic_exception_propagates(jina_embedding_instance):
    """Generic Exception propagates from get_multimodal_embeddings."""
    with patch.object(
        jina_embedding_instance.session,
        "post",
        side_effect=RuntimeError("unexpected error"),
    ):
        with pytest.raises(RuntimeError):
            jina_embedding_instance.get_multimodal_embeddings(
                [{"text": "x"}], with_metadata=False, timeout=5
            )


@pytest.mark.asyncio
async def test_jina_dimension_check_generic_exception_returns_empty(jina_embedding_instance):
    """JinaEmbedding.dimension_check should return [] on generic Exception."""
    with patch(
        "nexent.core.models.embedding_model.asyncio.to_thread",
        new_callable=AsyncMock,
        side_effect=RuntimeError("unexpected"),
    ):
        result = await jina_embedding_instance.dimension_check()
        assert result == []


@pytest.mark.asyncio
async def test_openai_dimension_check_generic_exception_returns_empty(openai_embedding_instance):
    """OpenAICompatibleEmbedding.dimension_check should return [] on generic Exception."""
    with patch(
        "nexent.core.models.embedding_model.asyncio.to_thread",
        new_callable=AsyncMock,
        side_effect=RuntimeError("unexpected"),
    ):
        result = await openai_embedding_instance.dimension_check()
        assert result == []


def test_openai_get_embeddings_connection_error_propagates(openai_embedding_instance):
    """ConnectionError propagates (only Timeout is caught in get_embeddings)."""
    with patch.object(
        openai_embedding_instance.session,
        "post",
        side_effect=requests.exceptions.ConnectionError(),
    ):
        with pytest.raises(requests.exceptions.ConnectionError):
            openai_embedding_instance.get_embeddings(
                ["x"], with_metadata=False, timeout=5
            )


def test_openai_get_embeddings_generic_exception_propagates(openai_embedding_instance):
    """Generic Exception propagates (only Timeout is caught in get_embeddings)."""
    with patch.object(
        openai_embedding_instance.session,
        "post",
        side_effect=RuntimeError("unexpected"),
    ):
        with pytest.raises(RuntimeError):
            openai_embedding_instance.get_embeddings(
                ["x"], with_metadata=False, timeout=5
            )


def test_openai_get_embeddings_http_error_not_caught(openai_embedding_instance):
    """HTTP errors should propagate (not be caught by the timeout handler)."""
    mock_resp = Mock()
    mock_resp.raise_for_status = Mock(side_effect=requests.HTTPError("Server error"))
    mock_resp.json = Mock(return_value={"data": []})

    with patch.object(
        openai_embedding_instance.session, "post", return_value=mock_resp
    ):
        with pytest.raises(requests.HTTPError):
            openai_embedding_instance.get_embeddings(
                ["x"], with_metadata=False, timeout=5
            )


def test_jina_get_embeddings_http_error_not_caught(jina_embedding_instance):
    """HTTP errors should propagate for JinaEmbedding too."""
    mock_resp = Mock()
    mock_resp.raise_for_status = Mock(side_effect=requests.HTTPError("Server error"))
    mock_resp.json = Mock(return_value={"data": []})

    with patch.object(
        jina_embedding_instance.session, "post", return_value=mock_resp
    ):
        with pytest.raises(requests.HTTPError):
            jina_embedding_instance.get_embeddings(
                ["x"], with_metadata=False, timeout=5
            )


def test_dashscope_get_embeddings_http_error_not_caught(dashscope_embedding_instance):
    """HTTP errors should propagate for DashScopeEmbedding too."""
    mock_resp = Mock()
    mock_resp.raise_for_status = Mock(side_effect=requests.HTTPError("Server error"))
    mock_resp.json = Mock(return_value={})

    with patch.object(
        dashscope_embedding_instance.session, "post", return_value=mock_resp
    ):
        with pytest.raises(requests.HTTPError):
            dashscope_embedding_instance.get_embeddings(
                ["x"], with_metadata=False, timeout=5
            )


def test_openai_prepare_input_with_list_unchanged(openai_embedding_instance):
    """_prepare_input should pass a list input through unchanged."""
    result = openai_embedding_instance._prepare_input(["a", "b"])
    assert result == {"model": "dummy-model", "input": ["a", "b"]}


def test_openai_get_embeddings_zero_retries_succeeds_first_try(openai_embedding_instance):
    """With retries=0, only one attempt is made."""
    mock_resp = Mock()
    mock_resp.raise_for_status = Mock()
    mock_resp.json.return_value = {"data": [{"embedding": [0.5]}]}

    with patch.object(
        openai_embedding_instance.session, "post", return_value=mock_resp
    ):
        result = openai_embedding_instance.get_embeddings(
            ["x"], with_metadata=False, timeout=10, retries=0
        )
        assert result == [[0.5]]
        openai_embedding_instance.session.post.assert_called_once()


def test_jina_get_embeddings_zero_retries_succeeds_first_try(jina_embedding_instance):
    """With retries=0, only one attempt is made."""
    mock_resp = Mock()
    mock_resp.raise_for_status = Mock()
    mock_resp.json.return_value = {"data": [{"embedding": [0.6]}]}

    with patch.object(
        jina_embedding_instance.session, "post", return_value=mock_resp
    ):
        result = jina_embedding_instance.get_embeddings(
            ["x"], with_metadata=False, timeout=10, retries=0
        )
        assert result == [[0.6]]
        jina_embedding_instance.session.post.assert_called_once()


def test_dashscope_make_request_invokes_session_post(dashscope_embedding_instance):
    """_make_request should call session.post with correct parameters."""
    mock_resp = Mock()
    mock_resp.raise_for_status = Mock()
    mock_resp.json.return_value = {"output": {"embeddings": [{"embedding": [0.1]}]}}

    with patch.object(
        dashscope_embedding_instance.session, "post", return_value=mock_resp
    ) as mock_post:
        result = dashscope_embedding_instance._make_request(
            {"model": "x", "input": {"contents": []}}, timeout=5
        )
        assert result["output"]["embeddings"][0]["embedding"] == [0.1]
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["timeout"] == 5
        assert call_kwargs["verify"] is True


def test_dashscope_make_request_raises_http_error(dashscope_embedding_instance):
    """_make_request should propagate HTTP errors."""
    mock_resp = Mock()
    mock_resp.raise_for_status = Mock(side_effect=requests.HTTPError("Bad Gateway"))
    mock_resp.json.return_value = {}

    with patch.object(
        dashscope_embedding_instance.session, "post", return_value=mock_resp
    ):
        with pytest.raises(requests.HTTPError):
            dashscope_embedding_instance._make_request(
                {"model": "x", "input": {}}, timeout=5
            )


def test_dashscope_get_multimodal_embeddings_timeout_exhausts_raises(dashscope_embedding_instance):
    """get_multimodal_embeddings should raise Timeout after exhausting retries."""
    with patch.object(
        dashscope_embedding_instance, "_make_request",
        side_effect=requests.exceptions.Timeout(),
    ):
        with pytest.raises(requests.exceptions.Timeout):
            dashscope_embedding_instance.get_multimodal_embeddings(
                [{"text": "x"}], with_metadata=False, timeout=None, retries=2, retry_timeout_step=1
            )
        timeouts = [call.kwargs.get("timeout")
                    for call in dashscope_embedding_instance._make_request.call_args_list]
        assert timeouts == [1, 2, 3]

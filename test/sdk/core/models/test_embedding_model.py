import pytest
import requests
import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

# Dynamically load the module directly by file path to avoid importing sdk/nexent/__init__
MODULE_NAME = "embedding_model_under_test"
MODULE_PATH = (
    Path(__file__).resolve().parents[4]
    / "sdk"
    / "nexent"
    / "core"
    / "models"
    / "embedding_model.py"
)
spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
embedding_model_module = importlib.util.module_from_spec(spec)
sys.modules[MODULE_NAME] = embedding_model_module
assert spec and spec.loader
spec.loader.exec_module(embedding_model_module)

OpenAICompatibleEmbedding = embedding_model_module.OpenAICompatibleEmbedding
JinaEmbedding = embedding_model_module.JinaEmbedding


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
    )


@pytest.fixture()
def jina_embedding_instance():
    """Return a JinaEmbedding instance with minimal viable attributes for tests."""

    return JinaEmbedding(api_key="dummy-key")


# ---------------------------------------------------------------------------
# Tests for dimension_check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dimension_check_success(openai_embedding_instance):
    """dimension_check should return embeddings when no exception is raised."""

    expected_embeddings = [[0.1, 0.2, 0.3]]

    with patch(
        "embedding_model_under_test.asyncio.to_thread",
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
        "embedding_model_under_test.asyncio.to_thread",
        new_callable=AsyncMock,
        side_effect=Exception("connection error"),
    ) as mock_to_thread:
        result = await openai_embedding_instance.dimension_check()

        assert result == []
        mock_to_thread.assert_awaited_once()


# ---------------------------------------------------------------------------
# Tests for JinaEmbedding.dimension_check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jina_dimension_check_success(jina_embedding_instance):
    """dimension_check should return embeddings when no exception is raised."""

    expected_embeddings = [[0.5, 0.4, 0.3]]

    with patch(
        "embedding_model_under_test.asyncio.to_thread",
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
        "embedding_model_under_test.asyncio.to_thread",
        new_callable=AsyncMock,
        side_effect=Exception("connection error"),
    ) as mock_to_thread:
        result = await jina_embedding_instance.dimension_check()

        assert result == []
        mock_to_thread.assert_awaited_once()


# ---------------------------------------------------------------------------
# Tests for OpenAICompatibleEmbedding.get_embeddings (retry, metadata, etc.)
# ---------------------------------------------------------------------------


def test_openai_get_embeddings_success_returns_list(openai_embedding_instance):
    """Should return list of embeddings when with_metadata is False."""

    fake_response = {"data": [{"embedding": [0.9, 0.8]}]}

    with patch(
        "embedding_model_under_test.OpenAICompatibleEmbedding._make_request",
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
        "embedding_model_under_test.OpenAICompatibleEmbedding._make_request",
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
        "embedding_model_under_test.OpenAICompatibleEmbedding._make_request",
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
        "embedding_model_under_test.OpenAICompatibleEmbedding._make_request",
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
        "embedding_model_under_test.JinaEmbedding.get_multimodal_embeddings",
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
        "embedding_model_under_test.JinaEmbedding.get_multimodal_embeddings",
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
        "embedding_model_under_test.JinaEmbedding.get_multimodal_embeddings",
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

    with patch(
        "embedding_model_under_test.requests.post", return_value=mock_resp
    ) as mock_post:
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

    with patch("embedding_model_under_test.requests.post", return_value=mock_resp) as mock_post:
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

    def side_effect(url, headers=None, json=None, timeout=None):
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

    with patch(
        "embedding_model_under_test.requests.post", side_effect=side_effect
    ) as mock_post:
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

    with patch(
        "embedding_model_under_test.requests.post",
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
        "embedding_model_under_test.asyncio.to_thread",
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
        "embedding_model_under_test.OpenAICompatibleEmbedding._make_request",
        side_effect=side_effect,
    ) as mock_make_request:
        result = openai_embedding_instance.get_embeddings(
            "hello-openai", with_metadata=False, timeout=3
        )

        assert captured["input"] == ["hello-openai"]
        assert result == [[0.21, 0.22]]
        mock_make_request.assert_called_once()


def test_openai_make_request_invokes_requests_post(openai_embedding_instance):
    """Cover OpenAI _make_request by patching requests.post path."""

    fake_response = {"data": [{"embedding": [7, 8]}]}

    mock_resp = Mock()
    mock_resp.raise_for_status = Mock()
    mock_resp.json = Mock(return_value=fake_response)

    with patch("embedding_model_under_test.requests.post", return_value=mock_resp) as mock_post:
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
        "embedding_model_under_test.asyncio.to_thread",
        new_callable=AsyncMock,
        side_effect=requests.exceptions.ConnectionError(),
    ):
        result = await openai_embedding_instance.dimension_check()

        assert result == []

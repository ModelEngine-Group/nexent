import pytest

from sdk.benchmark.generic.common.secret_refs import (
    ENV_REFERENCE_KEY,
    REDACTED_VALUE,
    environment_name_for_secret,
    externalize_sensitive_values,
    is_sensitive_key,
    resolve_env_references,
)


@pytest.mark.parametrize(
    "key",
    [
        "api_key",
        "exa_api_key",
        "tavily-api-key",
        "password",
        "ssh_password",
        "client_secret",
        "access_token",
        "authorization",
        "authorization_header",
        "headers",
        "custom_headers",
        "cookie",
    ],
)
def test_is_sensitive_key_matches_supported_patterns(key):
    assert is_sensitive_key(key)


@pytest.mark.parametrize(
    "key",
    ["max_tokens", "token_threshold", "secretary", "cookie_policy"],
)
def test_is_sensitive_key_avoids_unrelated_fields(key):
    assert not is_sensitive_key(key)


def test_resolve_env_references_resolves_nested_values():
    config = {
        "tools": [{
            "tool_params": {
                "exa_api_key": {ENV_REFERENCE_KEY: "EXA_API_KEY"},
            },
        }],
    }

    resolved = resolve_env_references(
        config,
        environ={"EXA_API_KEY": "resolved-secret"},
    )

    assert resolved["tools"][0]["tool_params"]["exa_api_key"] == "resolved-secret"
    assert config["tools"][0]["tool_params"]["exa_api_key"] == {
        ENV_REFERENCE_KEY: "EXA_API_KEY",
    }


@pytest.mark.parametrize("environment", [{}, {"EXA_API_KEY": ""}])
def test_resolve_env_references_rejects_missing_or_empty_values(environment):
    with pytest.raises(ValueError, match="EXA_API_KEY"):
        resolve_env_references(
            {ENV_REFERENCE_KEY: "EXA_API_KEY"},
            environ=environment,
        )


def test_resolve_env_references_rejects_invalid_reference_shape():
    with pytest.raises(ValueError, match="must be the only key"):
        resolve_env_references({
            ENV_REFERENCE_KEY: "EXA_API_KEY",
            "default": "plaintext-fallback",
        })


def test_externalize_sensitive_values_uses_stable_environment_names():
    safe_params, required_variables = externalize_sensitive_values(
        {
            "exa_api_key": "secret-exa",
            "api_key": "secret-generic",
            "password": "secret-password",
            "max_results": 3,
            "headers": {"Authorization": "secret-header"},
        },
        tool_name="exa_search",
    )

    assert safe_params == {
        "exa_api_key": {ENV_REFERENCE_KEY: "EXA_API_KEY"},
        "api_key": {ENV_REFERENCE_KEY: "EXA_SEARCH_API_KEY"},
        "password": {ENV_REFERENCE_KEY: "EXA_SEARCH_PASSWORD"},
        "max_results": 3,
        "headers": REDACTED_VALUE,
    }
    assert required_variables == {
        "EXA_API_KEY",
        "EXA_SEARCH_API_KEY",
        "EXA_SEARCH_PASSWORD",
    }


def test_environment_name_for_terminal_password():
    assert environment_name_for_secret("terminal", "password") == (
        "TERMINAL_PASSWORD"
    )

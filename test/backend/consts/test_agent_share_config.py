from consts import const


def test_agent_share_reuses_the_existing_auth_secret_without_new_configuration():
    assert not hasattr(const, "AGENT_SHARE_ENABLED")
    assert not hasattr(const, "AGENT_SHARE_TOKEN_SECRET")
    assert not hasattr(const, "AGENT_SHARE_RATE_LIMIT_ENABLED")
    assert not hasattr(const, "AGENT_SHARE_RATE_LIMIT_PER_MINUTE")
    assert hasattr(const, "SUPABASE_JWT_SECRET")


def test_agent_share_is_not_exposed_as_an_installation_parameter():
    from pathlib import Path

    installation_files = (
        "deploy/env/.env.example",
        "deploy/k8s/deploy.sh",
        "deploy/k8s/helm/nexent/charts/nexent-common/values.yaml",
        "deploy/k8s/helm/nexent/charts/nexent-common/templates/configmap.yaml",
        "deploy/k8s/helm/nexent/charts/nexent-common/templates/secrets.yaml",
    )

    for filename in installation_files:
        content = Path(filename).read_text(encoding="utf-8")
        assert "agentShare" not in content
        assert "AGENT_SHARE" not in content

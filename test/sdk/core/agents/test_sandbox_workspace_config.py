import pytest
from nexent.core.agents.sandbox import SandboxConfig


def test_bind_requires_posix_container_root():
    with pytest.raises(ValueError, match="container"):
        SandboxConfig.from_dict({"workspace_mode": "bind"})


@pytest.mark.parametrize("field,value", [("workspace_mode", "typo"), ("failure_policy", "ignore")])
def test_invalid_workspace_policy_is_rejected(field, value):
    with pytest.raises(ValueError):
        SandboxConfig.from_dict({field: value})


def test_defaults_preserve_existing_policy():
    config = SandboxConfig.from_dict({})
    assert config.workspace_mode == "legacy"
    assert config.failure_policy == "local"

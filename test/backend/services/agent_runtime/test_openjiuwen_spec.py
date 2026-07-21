from types import SimpleNamespace

import pytest

from backend.services.agent_runtime.openjiuwen_spec import build_openjiuwen_run_spec


def make_agent(agent_id, name, framework="openjiuwen", children=None):
    return SimpleNamespace(
        id=agent_id,
        name=name,
        description=f"{name} description",
        runtime_framework=framework,
        managed_agents=list(children or []),
    )


def test_build_openjiuwen_run_spec_preserves_recursive_parent_and_depth():
    grandchild = make_agent(3, "grandchild")
    child = make_agent(2, "child", children=[grandchild])
    root = make_agent(1, "root", children=[child])

    spec = build_openjiuwen_run_spec(root)

    assert (spec.agent_id, spec.parent_agent_id, spec.depth) == (1, None, 0)
    assert (spec.children[0].agent_id, spec.children[0].parent_agent_id, spec.children[0].depth) == (2, 1, 1)
    assert (
        spec.children[0].children[0].agent_id,
        spec.children[0].children[0].parent_agent_id,
        spec.children[0].children[0].depth,
    ) == (3, 2, 2)


def test_build_openjiuwen_run_spec_rejects_mixed_framework_tree():
    root = make_agent(1, "root", children=[make_agent(2, "child", "smolagents")])

    with pytest.raises(ValueError, match="framework 'smolagents'"):
        build_openjiuwen_run_spec(root)


def test_build_openjiuwen_run_spec_rejects_cycle_before_native_resources():
    root = make_agent(1, "root")
    child = make_agent(2, "child", children=[root])
    root.managed_agents.append(child)

    with pytest.raises(ValueError, match="Circular internal Agent relationship"):
        build_openjiuwen_run_spec(root)


def test_build_openjiuwen_run_spec_requires_persisted_agent_id():
    root = make_agent(None, "root")

    with pytest.raises(ValueError, match="persisted Agent ID"):
        build_openjiuwen_run_spec(root)

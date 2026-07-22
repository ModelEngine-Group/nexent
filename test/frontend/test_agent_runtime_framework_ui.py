from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"


def read(relative_path: str) -> str:
    return (FRONTEND / relative_path).read_text(encoding="utf-8")


def test_agent_info_selector_defaults_and_locks_after_save():
    detail = read("app/[locale]/agents/components/agentInfo/AgentGenerateDetail.tsx")
    store = read("stores/agentConfigStore.ts")

    assert 'value: "smolagents"' in detail
    assert 'value: "openjiuwen"' in detail
    assert "isRuntimeFrameworkLocked" in detail
    assert "updateSubAgentIds([])" in detail
    assert 'runtime_framework: "smolagents"' in store
    assert "isRuntimeFrameworkLocked: true" in store
    assert "Boolean(agent?.runtime_framework)" in store


def test_internal_agent_candidates_are_filtered_by_runtime_framework():
    component = read("app/[locale]/agents/components/agentConfig/CollaborativeAgent.tsx")

    assert "sameFrameworkInternalAgents" in component
    assert '(agent.runtime_framework || "smolagents") === runtimeFramework' in component
    assert "availableInternalAgents = sameFrameworkInternalAgents.filter" in component


def test_save_and_both_copy_paths_propagate_source_framework():
    save_guard = read("hooks/agent/useSaveGuard.ts")
    header = read("app/[locale]/agents/components/AgentSelectorHeader.tsx")
    agent_list = read("app/[locale]/agents/components/agentManage/AgentList.tsx")

    expected = 'runtime_framework: detail.runtime_framework || "smolagents"'
    assert 'runtime_framework: currentEditedAgent.runtime_framework || "smolagents"' in save_guard
    assert expected in header
    assert expected in agent_list


def test_runtime_framework_labels_exist_in_both_locales():
    english = read("public/locales/en/common.json")
    chinese = read("public/locales/zh/common.json")

    for locale in (english, chinese):
        assert '"agent.runtimeFramework.label"' in locale
        assert '"agent.runtimeFramework.immutableHint"' in locale
        assert '"agent.runtimeFramework.mismatch"' in locale

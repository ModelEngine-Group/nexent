import { beforeEach, describe, expect, it, vi } from "vitest";
import { compatibleCorePatch } from "@/lib/agentCore";
import { useAgentStore } from "@/stores/agentStore";
import { updateAgentInfo } from "@/services/agentConfigService";
import type { Agent } from "@/types/agentConfig";

vi.mock("@/services/agentConfigService", () => ({
  updateAgentInfo: vi.fn(),
  updateToolConfig: vi.fn(),
  searchToolConfig: vi.fn(),
}));

const agent: Agent = {
  id: "42",
  name: "test",
  model: "model",
  description: "unchanged",
  max_step: 10,
  provide_run_summary: true,
  enable_context_manager: true,
  permission: "EDIT",
  tools: [],
  skills: [],
  sub_agent_id_list: [8],
  sub_agent_relations: [{ agent_id: 8, version_no: 1 }],
  external_sub_agent_id_list: [9],
};

describe("Core configuration", () => {
  beforeEach(() => {
    vi.mocked(updateAgentInfo).mockResolvedValue({
      success: true,
      data: { agent_id: 42 },
      message: "",
      error: undefined,
    });
    useAgentStore.getState().initialize(agent);
  });

  it("preserves all settings through Jiuwen saves and a return to smolagents", async () => {
    useAgentStore.getState().updateAgentConfig({ agent_core: "jiuwen" });
    expect(await useAgentStore.getState().waitForIdle()).toBe(true);
    expect(updateAgentInfo).toHaveBeenCalledWith({
      agent_id: 42,
      agent_core: "jiuwen",
    });
    expect(useAgentStore.getState().editedAgent).toMatchObject({
      enable_context_manager: true,
      provide_run_summary: true,
      sub_agent_id_list: [8],
      sub_agent_relations: [{ agent_id: 8, version_no: 1 }],
      external_sub_agent_id_list: [9],
    });
    expect(useAgentStore.getState().editedAgent).toMatchObject({
      model: "model",
      description: "unchanged",
      tools: [],
      skills: [],
    });
    useAgentStore
      .getState()
      .updateAgentConfig({ enable_context_manager: true });
    await useAgentStore.getState().waitForIdle();
    expect(useAgentStore.getState().editedAgent?.enable_context_manager).toBe(
      true
    );
    useAgentStore.getState().updateAgentConfig({
      agent_core: "smolagents",
      enable_context_manager: true,
    });
    await useAgentStore.getState().waitForIdle();
    expect(useAgentStore.getState().editedAgent).toMatchObject({
      agent_core: "smolagents",
      enable_context_manager: true,
      sub_agent_id_list: [8],
    });
  });

  it("defaults legacy records and never mutates readonly configuration", async () => {
    useAgentStore.getState().initialize({ ...agent, permission: "READ_ONLY" });
    useAgentStore.getState().updateAgentConfig({ agent_core: "jiuwen" });
    await useAgentStore.getState().waitForIdle();
    expect(useAgentStore.getState().editedAgent?.agent_core).toBe("smolagents");
    expect(updateAgentInfo).not.toHaveBeenCalled();
  });

  it("rolls back a failed Core save and permits retry", async () => {
    vi.mocked(updateAgentInfo).mockResolvedValueOnce({
      success: false,
      data: null,
      message: "rejected",
      error: undefined,
    });
    useAgentStore.getState().updateAgentConfig({ agent_core: "jiuwen" });
    expect(await useAgentStore.getState().waitForIdle()).toBe(false);
    expect(useAgentStore.getState().editedAgent?.agent_core).toBe("smolagents");
    useAgentStore.getState().updateAgentConfig({ agent_core: "jiuwen" });
    expect(await useAgentStore.getState().waitForIdle()).toBe(true);
  });

  it("retains enabled guardrail and all its rules without changing caller input", () => {
    const rules = [
      { name: "rule", pattern: "secret", severity: "block" as const },
    ];
    const patch = {
      verification_config: {
        enabled: true,
        step_verification_enabled: true,
        final_verification_enabled: true,
        max_final_rounds: 2,
        strictness: "balanced" as const,
        fail_policy: "warn" as const,
        critical_events: [],
        guardrail_config: {
          enabled: true,
          rules,
          default_action: "pass" as const,
        },
      },
    };
    const result = compatibleCorePatch({ agent_core: "jiuwen" }, patch);
    expect(result.verification_config?.guardrail_config).toMatchObject({
      enabled: true,
      rules,
    });
    expect(patch.verification_config.guardrail_config.enabled).toBe(true);
    expect(compatibleCorePatch(null, { description: "same" })).toEqual({
      description: "same",
    });
  });
});

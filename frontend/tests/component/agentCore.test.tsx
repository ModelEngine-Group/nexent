// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { beforeEach, describe, expect, it, vi } from "vitest";
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

describe("Deployment-only Core preserves ordinary Agent settings", () => {
  beforeEach(() => {
    vi.mocked(updateAgentInfo).mockClear();
    vi.mocked(updateAgentInfo).mockResolvedValue({
      success: true,
      data: { agent_id: 42 },
      message: "",
      error: undefined,
    });
    useAgentStore.getState().initialize(agent);
  });

  it("drops a legacy saved Core and persists CM without touching resources", async () => {
    const legacy = { ...agent, agent_core: "jiuwen" };
    useAgentStore.getState().initialize(legacy);
    expect(useAgentStore.getState().editedAgent).not.toHaveProperty(
      "agent_core"
    );
    useAgentStore
      .getState()
      .updateAgentConfig({ enable_context_manager: false });
    expect(await useAgentStore.getState().waitForIdle()).toBe(true);
    expect(updateAgentInfo).toHaveBeenCalledExactlyOnceWith({
      agent_id: 42,
      enable_context_manager: false,
    });
    expect(useAgentStore.getState().editedAgent).toMatchObject({
      enable_context_manager: false,
      provide_run_summary: true,
      model: "model",
      description: "unchanged",
      tools: [],
      skills: [],
      sub_agent_id_list: [8],
      sub_agent_relations: [{ agent_id: 8, version_no: 1 }],
      external_sub_agent_id_list: [9],
    });
    expect(useAgentStore.getState().savedAgent).not.toHaveProperty(
      "agent_core"
    );
  });

  it("never mutates read-only CM or resource configuration", async () => {
    useAgentStore.getState().initialize({ ...agent, permission: "READ_ONLY" });
    useAgentStore
      .getState()
      .updateAgentConfig({ enable_context_manager: false });
    await useAgentStore.getState().waitForIdle();
    expect(useAgentStore.getState().editedAgent?.enable_context_manager).toBe(
      true
    );
    expect(updateAgentInfo).not.toHaveBeenCalled();
  });

  it("rolls back a failed CM save and permits retry", async () => {
    vi.mocked(updateAgentInfo).mockResolvedValueOnce({
      success: false,
      data: null,
      message: "rejected",
      error: undefined,
    });
    useAgentStore
      .getState()
      .updateAgentConfig({ enable_context_manager: false });
    expect(await useAgentStore.getState().waitForIdle()).toBe(false);
    expect(useAgentStore.getState().editedAgent?.enable_context_manager).toBe(
      true
    );
    useAgentStore
      .getState()
      .updateAgentConfig({ enable_context_manager: false });
    expect(await useAgentStore.getState().waitForIdle()).toBe(true);
    expect(useAgentStore.getState().editedAgent?.enable_context_manager).toBe(
      false
    );
  });

  it("retains guardrail settings without rewriting the caller patch", async () => {
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
    useAgentStore.getState().updateAgentConfig(patch);
    expect(await useAgentStore.getState().waitForIdle()).toBe(true);
    expect(updateAgentInfo).toHaveBeenCalledExactlyOnceWith({
      agent_id: 42,
      ...patch,
    });
    expect(patch.verification_config.guardrail_config.enabled).toBe(true);
    expect(
      useAgentStore.getState().editedAgent?.verification_config
        ?.guardrail_config
    ).toMatchObject({
      enabled: true,
      rules,
    });
  });
});

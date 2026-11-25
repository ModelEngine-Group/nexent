// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { InstalledResourceBindingCard } from "@/app/newchat/ui/installed-resource-binding-card";

const mocks = vi.hoisted(() => ({
  waitForIdle: vi.fn(async () => false),
  searchToolConfig: vi.fn(),
  updateToolConfig: vi.fn(),
}));
vi.mock("@assistant-ui/react", () => ({
  useAui: () => ({}),
  useAuiState: () => false,
}));
vi.mock("@tanstack/react-query", () => ({ useQueryClient: () => ({}) }));
vi.mock("@/app/newchat/ui/use-nl2agent-knowledge-recommendations", () => ({
  useNl2AgentKnowledgeRecommendations: () => ({ data: undefined, isFetching: false, isError: false, refetch: vi.fn() }),
}));
vi.mock("@/contexts/nl2AgentFlow", () => ({
  useNl2AgentFlow: () => ({
    registerCard: vi.fn(),
    isCardInteractive: () => true,
  }),
}));
vi.mock("@/stores/agentStore", () => ({
  useAgentStore: (selector: (state: object) => unknown) =>
    selector({ waitForIdle: mocks.waitForIdle }),
}));
vi.mock("@/hooks/agent/useToolList", () => ({
  useToolList: () => ({
    availableTools: [{ id: "1", name: "Custom tool", initParams: [] }],
  }),
}));
vi.mock("@/services/agentConfigService", () => ({
  searchToolConfig: mocks.searchToolConfig,
  updateToolConfig: mocks.updateToolConfig,
}));
vi.mock("@/app/newchat/ui/nl2agent-binding-item", () => ({
  Nl2AgentBindingItem: () => null,
}));
vi.mock("@/app/agents/components/capability/tool/ToolConfigModal", () => ({
  default: () => <div role="dialog" />,
}));
vi.mock("@/app/agents/components/capability/skill/SkillConfigModal", () => ({
  default: () => <div role="dialog" />,
}));

it("stops bind-triggered configuration when pending Agent changes cannot be saved", async () => {
  render(
    <InstalledResourceBindingCard
      payload={{
        subtype: "installed_resource_binding",
        agent_id: 42,
        protocol_version: 2,
        card_id: "binding",
        state_version: 1,
        resources: [
          {
            candidate: {
              candidate_ref: "tool:1",
              resource_type: "tool",
              source: "LOCAL_TOOL",
              name: "Custom tool",
              description: "",
              requirement_ids: [],
              score: 1,
            },
            recommendation: "recommended",
            is_bound: false,
            config: [],
            has_config: true,
            form_kind: "TOOL_CONFIG",
          },
        ],
      }}
    />
  );
  fireEvent.click(screen.getByRole("button", { name: /Bind selected/ }));
  await screen.findByText(
    "Save the pending Agent changes before binding resources."
  );
  expect(mocks.waitForIdle).toHaveBeenCalledOnce();
  expect(mocks.searchToolConfig).not.toHaveBeenCalled();
  expect(mocks.updateToolConfig).not.toHaveBeenCalled();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Bind selected/ })).toBeEnabled();
});

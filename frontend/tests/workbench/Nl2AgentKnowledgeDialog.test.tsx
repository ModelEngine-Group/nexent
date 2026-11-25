// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { InstalledResourceBindingCard } from "@/app/newchat/ui/installed-resource-binding-card";
import type { Nl2aUnifiedResourcesPayload } from "@/app/newchat/adapter/remote-chat-model-adapter";
import type { Nl2AgentKnowledgePreparation } from "@/types/nl2AgentKnowledge";

const mocks = vi.hoisted(() => ({
  toolName: "knowledge_base_search",
  read: vi.fn(async () => ({ success: true, data: { params: {} } })),
  write: vi.fn(),
  register: vi.fn(),
  drafts: new Map(),
  recommendations: undefined as Nl2AgentKnowledgePreparation[] | undefined,
  loading: false,
  recommendationError: false,
}));
vi.mock("@assistant-ui/react", () => ({
  useAui: () => ({
    thread: () => ({
      composer: () => ({ getState: () => ({ runConfig: {} }) }),
    }),
  }),
  useAuiState: () => false,
}));
vi.mock("@tanstack/react-query", () => ({ useQueryClient: () => ({}) }));
vi.mock("@/hooks/useConfig", () => ({
  useConfig: () => ({ data: undefined }),
}));
vi.mock("@/app/newchat/ui/use-nl2agent-knowledge-recommendations", () => ({
  useNl2AgentKnowledgeRecommendations: () => ({
    data: mocks.recommendations,
    isFetching: mocks.loading,
    isError: mocks.recommendationError,
    refetch: vi.fn(),
  }),
}));
vi.mock("@/contexts/nl2AgentFlow", () => ({
  useNl2AgentFlow: () => ({
    registerCard: mocks.register,
    isCardInteractive: () => true,
    resourceDrafts: mocks.drafts,
    sessionGeneration: 1,
  }),
}));
vi.mock("@/hooks/agent/useToolList", () => ({
  useToolList: () => ({
    availableTools: [
      { id: "1", name: mocks.toolName, source: "local", initParams: [] },
    ],
  }),
}));
vi.mock("@/hooks/useKnowledgeBaseSelector", () => ({
  useKnowledgeBasesForToolConfig: () => ({
    data: [{ id: "1", index_name: "docs", name: "Docs" }],
    isLoading: false,
    isError: false,
  }),
}));
vi.mock("@/stores/agentStore", () => ({
  useAgentStore: (selector: (state: object) => unknown) =>
    selector({ waitForIdle: async () => true, currentAgentId: 42 }),
}));
vi.mock("@/services/agentConfigService", () => ({
  searchToolConfig: mocks.read,
  updateToolConfig: mocks.write,
}));
vi.mock("@/app/agents/components/capability/tool/ToolConfigModal", () => ({
  default: () => null,
}));
vi.mock("@/app/agents/components/capability/skill/SkillConfigModal", () => ({
  default: () => null,
}));
vi.mock("@/components/resource-picker/KnowledgeDrawer", () => ({
  KnowledgeDrawer: ({
    onClose,
    onConfirm,
    selectedIds,
  }: {
    onClose: () => void;
    onConfirm: (items: object[]) => void;
    selectedIds?: string[];
  }) => (
    <div
      role="dialog"
      aria-label="Knowledge configuration"
      data-selected={selectedIds?.join(",")}
    >
      <button onClick={onClose}>Cancel knowledge</button>
      <button
        onClick={() =>
          onConfirm([{ id: "1", index_name: "docs", name: "Docs" }])
        }
      >
        Confirm knowledge
      </button>
      <button onClick={() => onConfirm([])}>Clear knowledge</button>
    </div>
  ),
}));

function payload(shared = false): Nl2aUnifiedResourcesPayload {
  const ids = shared ? ["r1", "r2"] : ["r1"];
  return {
    subtype: "requirement_resources",
    protocol_version: 2,
    purpose: "generate",
    agent_id: 42,
    conversation_id: "c",
    card_id: "knowledge-card",
    state_version: 1,
    run_id: "run",
    requirements: ids.map((requirement_id) => ({
      requirement_id,
      query: requirement_id,
      required: true,
      coverage_status: "covered",
      covered_resources: [{ candidate_ref: "tool:1", name: mocks.toolName }],
      installable_resources: [],
    })),
    resources: [
      {
        candidate: {
          candidate_ref: "tool:1",
          resource_type: "tool",
          source: "LOCAL_TOOL",
          name: mocks.toolName,
          description: "Search knowledge",
          requirement_ids: ids,
          score: 0.9,
        },
        recommendation: "recommended",
        is_bound: false,
        has_config: true,
        form_kind: "TOOL_CONFIG",
        config: [],
      },
    ],
  };
}
beforeEach(() => {
  vi.clearAllMocks();
  mocks.drafts.clear();
  mocks.toolName = "knowledge_base_search";
  mocks.recommendations = undefined;
  mocks.loading = false;
  mocks.recommendationError = false;
});

it("shows recommended defaults and respects a manually cleared selection on reopen", async () => {
  mocks.recommendations = [
    {
      candidate_ref: "tool:1",
      tool_name: "knowledge_base_search",
      recommendations: [
        { id: "1", binding_value: "docs", name: "Docs", score: 0.9 },
      ],
      selected_values: ["docs"],
      selection_source: "recommended",
      settings: {},
      models: { embedding_model_id: 11 },
      mode: "hybrid",
    },
  ];
  const card = payload();
  render(<InstalledResourceBindingCard payload={card} unifiedPayload={card} />);
  expect(screen.getByText("Recommended knowledge bases:")).toBeVisible();
  expect(screen.getByText("Docs")).toBeVisible();
  fireEvent.click(
    screen.getByRole("button", { name: "Select knowledge bases" })
  );
  expect(await screen.findByRole("dialog")).toHaveAttribute(
    "data-selected",
    "1"
  );
  fireEvent.click(screen.getByRole("button", { name: "Clear knowledge" }));
  expect(screen.queryByText("Docs")).toBeNull();
  expect(screen.getByText("Selected knowledge bases:")).toBeVisible();
  fireEvent.click(
    screen.getByRole("button", { name: "Select knowledge bases" })
  );
  expect(await screen.findByRole("dialog")).toHaveAttribute(
    "data-selected",
    ""
  );
  expect(mocks.write).not.toHaveBeenCalled();
});

it("pauses binding while recommendations load and allows manual configuration after failure", () => {
  mocks.loading = true;
  const card = payload();
  const { rerender } = render(
    <InstalledResourceBindingCard payload={card} unifiedPayload={card} />
  );
  expect(
    screen.getByRole("button", { name: "Select knowledge bases" })
  ).toBeDisabled();
  expect(screen.getByRole("button", { name: /Bind selected/ })).toBeDisabled();
  mocks.loading = false;
  mocks.recommendationError = true;
  rerender(
    <InstalledResourceBindingCard payload={card} unifiedPayload={card} />
  );
  expect(
    screen.getByRole("button", { name: "Select knowledge bases" })
  ).toBeEnabled();
  expect(screen.getByRole("alert")).toBeVisible();
});

it.each(["knowledge_base_search", "aidp_search"])(
  "opens %s configuration while other card operations remain locked, then cancel restores them",
  async (name) => {
    mocks.toolName = name;
    const card = payload();
    render(
      <InstalledResourceBindingCard payload={card} unifiedPayload={card} />
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Select knowledge bases" })
    );
    expect(await screen.findByRole("dialog")).toBeVisible();
    expect(screen.getByRole("checkbox")).toBeDisabled();
    expect(
      screen.getByRole("button", { name: /Bind selected/ })
    ).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel knowledge" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("checkbox")).toBeEnabled();
    expect(mocks.write).not.toHaveBeenCalled();
  }
);

it("opens only one drawer when a shared tool is configured from its second requirement and retains the local selection", async () => {
  const card = payload(true);
  render(<InstalledResourceBindingCard payload={card} unifiedPayload={card} />);
  fireEvent.click(
    screen.getAllByRole("button", { name: "Select knowledge bases" })[1]
  );
  await screen.findByRole("dialog");
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "Confirm knowledge" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.getAllByText("Docs")).toHaveLength(2);
  fireEvent.click(
    screen.getAllByRole("button", { name: "Select knowledge bases" })[1]
  );
  expect(await screen.findByRole("dialog")).toBeVisible();
  expect(mocks.read).toHaveBeenCalledTimes(1);
  expect(mocks.write).not.toHaveBeenCalled();
});

it("shows a loading failure without leaving the card locked when configuration cannot be read", async () => {
  mocks.read.mockRejectedValueOnce(new Error("Unavailable"));
  const card = payload();
  render(<InstalledResourceBindingCard payload={card} unifiedPayload={card} />);
  fireEvent.click(
    screen.getByRole("button", { name: "Select knowledge bases" })
  );
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Failed to load the current resource configuration."
    )
  );
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.getByRole("checkbox")).toBeEnabled();
  expect(mocks.write).not.toHaveBeenCalled();
});

// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { InstalledResourceBindingCard } from "@/app/newchat/ui/installed-resource-binding-card";
import type { Skill, Tool } from "@/types/agentConfig";
import type { Nl2aUnifiedResourcesPayload } from "@/app/newchat/adapter/remote-chat-model-adapter";

const mocks = vi.hoisted(() => ({
  append: vi.fn(),
  update: vi.fn(async (id: number) => {
    mocks.boundIds.add(id);
    return { success: true };
  }),
  boundIds: new Set<number>(),
  currentAgentId: 42,
  savedAgent: null as { skills: Skill[]; tools: Tool[] } | null,
  editedAgent: null as { skills: Skill[]; tools: Tool[] } | null,
  tools: [] as {
    id: string;
    name: string;
    source: string;
    initParams: unknown[];
  }[],
  drafts: new Map(),
  register: vi.fn(),
  tool: { id: "1", name: "Search", source: "local", initParams: [] },
}));
vi.mock("@assistant-ui/react", () => ({
  useAui: () => ({
    thread: () => ({
      append: mocks.append,
      composer: () => ({ getState: () => ({ runConfig: {} }) }),
    }),
  }),
  useAuiState: () => false,
}));
vi.mock("@/app/newchat/ui/use-nl2agent-knowledge-recommendations", () => ({
  useNl2AgentKnowledgeRecommendations: () => ({
    data: undefined,
    isFetching: false,
    isError: false,
    refetch: vi.fn(),
  }),
}));
vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({
    getQueryData: () => [],
    setQueryData: vi.fn(),
    invalidateQueries: vi.fn(async () => {}),
  }),
}));
vi.mock("@/contexts/nl2AgentFlow", () => ({
  useNl2AgentFlow: () => ({
    registerCard: mocks.register,
    isCardInteractive: () => true,
    resourceDrafts: mocks.drafts,
    requestConfigFocus: vi.fn(),
    sessionGeneration: 1,
  }),
}));
vi.mock("@/hooks/agent/useToolList", () => ({
  useToolList: () => ({ availableTools: mocks.tools }),
}));
vi.mock("@/hooks/useKnowledgeBaseSelector", () => ({
  useKnowledgeBasesForToolConfig: () => ({
    data: [],
    isLoading: false,
    isError: false,
  }),
}));
vi.mock("@/stores/agentStore", () => ({
  useAgentStore: (selector: (value: object) => unknown) =>
    selector({
      waitForIdle: async () => true,
      currentAgentId: mocks.currentAgentId,
      savedAgent: mocks.savedAgent,
      editedAgent: mocks.editedAgent,
      applyPersistedResourceBindings: () => true,
      replaceServerSnapshot: () => true,
    }),
}));
vi.mock("@/services/agentConfigService", () => ({
  updateToolConfig: mocks.update,
  searchAgentInfo: async () => ({
    success: true,
    data: {
      tools: mocks.tools.filter((tool) => mocks.boundIds.has(Number(tool.id))),
      skills: [],
    },
  }),
}));
vi.mock("@/app/agents/components/capability/tool/ToolConfigModal", () => ({
  default: () => null,
}));
vi.mock("@/app/agents/components/capability/skill/SkillConfigModal", () => ({
  default: () => null,
}));

const payload: Nl2aUnifiedResourcesPayload = {
  subtype: "requirement_resources",
  protocol_version: 2,
  purpose: "generate",
  agent_id: 42,
  conversation_id: "c",
  card_id: "card",
  state_version: 1,
  run_id: "run",
  requirements: [1, 2, 3].map((id) => ({
    requirement_id: `r${id}`,
    query: `Requirement ${id}`,
    required: true,
    coverage_status: id === 3 ? "uncovered" : "covered",
    installable_resources: [],
    covered_resources:
      id === 3 ? [] : [{ candidate_ref: "tool:1", name: "Search" }],
  })),
  resources: [
    {
      candidate: {
        candidate_ref: "tool:1",
        resource_type: "tool",
        source: "LOCAL_TOOL",
        name: "Search",
        description: "Search websites",
        requirement_ids: ["r1", "r2"],
        score: 0.9,
      },
      recommendation: "recommended",
      is_bound: false,
      has_config: false,
      form_kind: "TOOL_CONFIG",
      config: [],
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.drafts.clear();
  mocks.boundIds.clear();
  mocks.currentAgentId = 42;
  mocks.savedAgent = null;
  mocks.editedAgent = null;
  mocks.tools = [
    mocks.tool,
    { id: "2", name: "Alternative", source: "local", initParams: [] },
  ];
});

it("keeps per-requirement choices independent and binds a shared resource once despite another gap", async () => {
  render(
    <InstalledResourceBindingCard payload={payload} unifiedPayload={payload} />
  );
  const checkboxes = screen.getAllByRole("checkbox");
  expect(checkboxes).toHaveLength(2);
  fireEvent.click(checkboxes[0]);
  expect(checkboxes[0]).not.toBeChecked();
  expect(checkboxes[1]).toBeChecked();
  expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: /Bind selected.*1/ }));
  await waitFor(() =>
    expect(mocks.update).toHaveBeenCalledExactlyOnceWith(1, 42, {}, true)
  );
  expect(mocks.append).not.toHaveBeenCalled();
});

it("pauses actual binding controls while editing and restores selections on cancel", () => {
  render(
    <InstalledResourceBindingCard payload={payload} unifiedPayload={payload} />
  );
  fireEvent.click(
    screen.getAllByRole("button", { name: "Edit requirement" })[0]
  );
  expect(
    screen
      .getAllByRole("checkbox")
      .every((item) => item.hasAttribute("disabled"))
  ).toBe(true);
  expect(screen.queryByRole("button", { name: /Bind selected/ })).toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "nl2agent.unified.cancel" })
  );
  expect(
    screen
      .getAllByRole("checkbox")
      .every((item) => !item.hasAttribute("disabled"))
  ).toBe(true);
  expect(mocks.update).not.toHaveBeenCalled();
});

it("does not require repairing an unused binding when a ready alternative already covers the requirement", () => {
  const ready: Nl2aUnifiedResourcesPayload = {
    ...payload,
    requirements: [
      {
        ...payload.requirements[0],
        covered_resources: [
          { candidate_ref: "tool:1", name: "Search" },
          { candidate_ref: "skill:90", name: "Unused skill" },
        ],
      },
    ],
    resources: [
      { ...payload.resources[0], is_bound: true, readiness: "ready" },
      {
        candidate: {
          candidate_ref: "skill:90",
          resource_type: "skill",
          source: "INSTALLED_SKILL",
          name: "Unused skill",
          description: "Search",
          requirement_ids: ["r1"],
          score: 0.8,
        },
        recommendation: "optional",
        is_bound: true,
        readiness: "not_ready",
        form_kind: "SKILL_CONFIG",
        config: [],
      },
    ],
  };
  render(
    <InstalledResourceBindingCard payload={ready} unifiedPayload={ready} />
  );
  expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
  expect(mocks.update).not.toHaveBeenCalled();
});

it("keeps continuation disabled when the only existing binding is not ready", () => {
  const invalid: Nl2aUnifiedResourcesPayload = {
    ...payload,
    requirements: [payload.requirements[0]],
    resources: [
      { ...payload.resources[0], is_bound: true, readiness: "not_ready" },
    ],
  };
  render(
    <InstalledResourceBindingCard payload={invalid} unifiedPayload={invalid} />
  );
  expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  expect(mocks.update).not.toHaveBeenCalled();
});

it("keeps ready requirements in place, locks bound selections and accumulates later bindings", async () => {
  const alternative: Nl2aUnifiedResourcesPayload["resources"][number] = {
    ...payload.resources[0],
    candidate: {
      ...payload.resources[0].candidate,
      resource_type: "tool",
      candidate_ref: "tool:2",
      name: "Alternative",
      requirement_ids: ["r1"],
    },
    recommendation: "optional" as const,
    config: [],
    form_kind: "TOOL_CONFIG",
  };
  const single: Nl2aUnifiedResourcesPayload = {
    ...payload,
    requirements: [
      {
        ...payload.requirements[0],
        covered_resources: [
          { candidate_ref: "tool:1", name: "Search" },
          { candidate_ref: "tool:2", name: "Alternative" },
        ],
      },
    ],
    resources: [payload.resources[0], alternative],
  };
  render(
    <InstalledResourceBindingCard payload={single} unifiedPayload={single} />
  );
  expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: /Bind selected.*1/ }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled()
  );
  expect(screen.getByText("Requirement 1", { exact: true })).toBeVisible();
  expect(screen.getByRole("checkbox", { name: "Search" })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "Search" })).toBeDisabled();
  expect(
    screen.queryByRole("button", {
      name: /readyRequirements|Ready requirements/,
    })
  ).toBeNull();
  const additional = screen.getByRole("checkbox", {
    name: "Alternative",
  });
  expect(additional).toBeEnabled();
  expect(additional).not.toBeChecked();
  fireEvent.click(additional);
  fireEvent.click(screen.getByRole("button", { name: /Bind selected.*1/ }));
  await waitFor(() => expect(additional).toBeDisabled());
  expect(additional).toBeChecked();
  expect(mocks.update.mock.calls.map(([id]) => id)).toEqual([1, 2]);
  expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
  expect(screen.getByText("Requirement 1", { exact: true })).toBeVisible();
});

const savedSkill: Skill = {
  skill_id: 7,
  name: "Canvas",
  description: "Draw images",
  source: "local",
  config_schemas: [],
  config_values: {},
};
const skillPayload = (): Nl2aUnifiedResourcesPayload => ({
  ...payload,
  requirements: [1, 2].map((id) => ({
    ...payload.requirements[0],
    requirement_id: `r${id}`,
    query: `Skill requirement ${id}`,
    covered_resources: [{ candidate_ref: "skill:7", name: "Canvas" }],
  })),
  resources: [
    {
      candidate: {
        candidate_ref: "skill:7",
        resource_type: "skill",
        source: "INSTALLED_SKILL",
        name: "Canvas",
        description: "Draw images",
        requirement_ids: ["r1", "r2"],
        score: 0.9,
      },
      recommendation: "recommended",
      is_bound: false,
      has_config: false,
      form_kind: "SKILL_CONFIG",
      config: [],
    },
  ],
});

it("matches saved Skills by ID rather than by a duplicate name", () => {
  mocks.savedAgent = { tools: [], skills: [{ ...savedSkill, skill_id: 8 }] };
  const card = skillPayload();
  render(<InstalledResourceBindingCard payload={card} unifiedPayload={card} />);
  expect(screen.getAllByRole("checkbox", { name: "Canvas" })[0]).toBeEnabled();
  expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
});

it("reconciles a stale card with saved Skills and locks every shared occurrence without rebinding", async () => {
  mocks.savedAgent = { tools: [], skills: [savedSkill] };
  const card = skillPayload();
  render(<InstalledResourceBindingCard payload={card} unifiedPayload={card} />);
  const boxes = screen.getAllByRole("checkbox", { name: "Canvas" });
  await waitFor(() => boxes.forEach((box) => expect(box).toBeDisabled()));
  boxes.forEach((box) => expect(box).toBeChecked());
  expect(
    screen.getByRole("button", { name: /Bind selected.*0/ })
  ).toBeDisabled();
  expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
  expect(mocks.update).not.toHaveBeenCalled();
});

it("waits for a saved Skill snapshot rather than locking an unsaved right-panel choice", async () => {
  mocks.savedAgent = { tools: [], skills: [] };
  mocks.editedAgent = { tools: [], skills: [savedSkill] };
  const card = skillPayload();
  const view = render(
    <InstalledResourceBindingCard payload={card} unifiedPayload={card} />
  );
  expect(screen.getAllByRole("checkbox", { name: "Canvas" })[0]).toBeEnabled();
  expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  mocks.savedAgent = { tools: [], skills: [savedSkill] };
  view.rerender(
    <InstalledResourceBindingCard payload={card} unifiedPayload={card} />
  );
  await waitFor(() =>
    expect(
      screen.getAllByRole("checkbox", { name: "Canvas" })[0]
    ).toBeDisabled()
  );
  expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
  mocks.savedAgent = { tools: [], skills: [] };
  view.rerender(
    <InstalledResourceBindingCard payload={card} unifiedPayload={card} />
  );
  await waitFor(() =>
    expect(screen.getAllByRole("checkbox", { name: "Canvas" })[0]).toBeEnabled()
  );
  expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
});

it.each(["different-agent", "historical"])(
  "does not apply saved Skills to a %s card",
  (mode) => {
    mocks.savedAgent = { tools: [], skills: [savedSkill] };
    if (mode === "different-agent") mocks.currentAgentId = 43;
    const card = skillPayload();
    render(
      <InstalledResourceBindingCard
        payload={card}
        unifiedPayload={card}
        disabled={mode === "historical"}
      />
    );
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    expect(
      screen.queryByText("Bound", { exact: true })
    ).not.toBeInTheDocument();
  }
);

it("keeps saved Skills with missing required values bound but not ready", async () => {
  mocks.savedAgent = {
    tools: [],
    skills: [
      {
        ...savedSkill,
        config_schemas: [
          {
            name: "token",
            type: "string",
            required: true,
            value: "default-token",
          },
        ],
        config_values: { token: null },
      },
    ],
  };
  const card = skillPayload();
  const view = render(
    <InstalledResourceBindingCard payload={card} unifiedPayload={card} />
  );
  await waitFor(() =>
    expect(
      screen.getAllByRole("checkbox", { name: "Canvas" })[0]
    ).toBeDisabled()
  );
  expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  mocks.savedAgent = {
    tools: [],
    skills: [
      {
        ...savedSkill,
        config_schemas: [{ name: "token", type: "string", required: true }],
        config_values: { token: "configured" },
      },
    ],
  };
  view.rerender(
    <InstalledResourceBindingCard payload={card} unifiedPayload={card} />
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled()
  );
});

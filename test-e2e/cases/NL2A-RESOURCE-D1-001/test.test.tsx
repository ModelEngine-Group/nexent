// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { InstalledResourceBindingCard } from "@/app/newchat/ui/installed-resource-binding-card";
import type { Nl2aRecommendedResource } from "@/app/newchat/adapter/remote-chat-model-adapter";

const mock = vi.hoisted(() => ({
  append: vi.fn(),
  updateToolConfig: vi.fn(),
  saveSkillInstance: vi.fn(),
  searchToolConfig: vi.fn(),
  searchAgentInfo: vi.fn(),
  waitForIdle: vi.fn(),
  apply: vi.fn(),
  replace: vi.fn(),
  refetch: vi.fn(),
  registerCard: vi.fn(),
  submitCard: vi.fn(),
  markResourcesBound: vi.fn(),
  requestConfigFocus: vi.fn(),
  invalidateQueries: vi.fn(),
  setQueryData: vi.fn(),
  tools: [] as any[],
  knowledge: [] as any[],
  editedAgent: undefined as any,
  knowledgeError: false,
  knowledgeLoading: false,
}));

vi.mock("@/app/i18n", () => ({
  default: { language: "en", t: (key: string) => key },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback: string) => fallback ?? _key,
  }),
}));
vi.mock("@assistant-ui/react", () => ({
  useAui: () => ({
    thread: () => ({
      append: mock.append,
      composer: () => ({ getState: () => ({ runConfig: {} }) }),
    }),
  }),
  useAuiState: () => false,
}));
vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({
    getQueryData: ([key]: string[]) => (key === "tools" ? mock.tools : []),
    setQueryData: mock.setQueryData,
    invalidateQueries: mock.invalidateQueries,
  }),
}));
vi.mock("@/contexts/nl2AgentFlow", () => ({
  useNl2AgentFlow: () => ({
    agentId: 42,
    failedPromptFields: [],
    phase: "binding",
    registerCard: mock.registerCard,
    submitCard: mock.submitCard,
    markResourcesBound: mock.markResourcesBound,
    requestConfigFocus: mock.requestConfigFocus,
    isCardInteractive: () => true,
  }),
}));
vi.mock("@/hooks/agent/useToolList", () => ({
  useToolList: () => ({
    availableTools: mock.tools,
    isFetching: false,
    isError: false,
  }),
}));
vi.mock("@/hooks/useKnowledgeBaseSelector", () => ({
  useKnowledgeBasesForToolConfig: () => ({
    data: mock.knowledge,
    isLoading: mock.knowledgeLoading,
    isError: mock.knowledgeError,
    refetch: mock.refetch,
  }),
}));
vi.mock("@/stores/agentStore", () => ({
  useAgentStore: (selector: any) =>
    selector({
      currentAgentId: 42,
      editedAgent: mock.editedAgent,
      waitForIdle: mock.waitForIdle,
      applyPersistedResourceBindings: mock.apply,
      replaceServerSnapshot: mock.replace,
    }),
}));
vi.mock("@/services/agentConfigService", () => ({
  updateToolConfig: mock.updateToolConfig,
  saveSkillInstance: mock.saveSkillInstance,
  searchToolConfig: mock.searchToolConfig,
  searchAgentInfo: mock.searchAgentInfo,
}));
vi.mock("@/app/agents/components/capability/tool/ToolConfigModal", () => ({
  default: () => <div role="dialog">Tool configuration</div>,
}));
vi.mock("@/app/agents/components/capability/skill/SkillConfigModal", () => ({
  default: () => <div role="dialog">Skill configuration</div>,
}));
vi.mock("@/components/resource-picker/KnowledgeDrawer", () => ({
  KnowledgeDrawer: (props: any) => (
    <div role="dialog" aria-label="Knowledge selection">
      <span>Selected: {props.selectedIds.join(",")}</span>
      <span>Limit: {props.maxSelect ?? "none"}</span>
      <button onClick={() => props.onConfirm(props.knowledgeBases.slice(0, 1))}>
        Choose policy
      </button>
      <button onClick={() => props.onConfirm([])}>Choose none</button>
      <button onClick={props.onClose}>Cancel selection</button>
    </div>
  ),
}));

function resource(
  name: string,
  id = 1,
  type: "tool" | "skill" = "tool",
  config: any[] = [],
): Nl2aRecommendedResource {
  return {
    candidate: {
      candidate_ref: `${type}:${id}`,
      resource_type: type,
      source: type === "skill" ? "INSTALLED_SKILL" : "LOCAL_TOOL",
      name,
      description: `${name} internal description`,
      requirement_ids: ["policy"],
      score: 0.9,
    },
    config,
    recommendation: "recommended",
    is_bound: false,
  } as Nl2aRecommendedResource;
}

function show(resources: Nl2aRecommendedResource[]) {
  mock.tools = resources
    .filter((item) => item.candidate.resource_type === "tool")
    .map((item) => ({
      id: item.candidate.candidate_ref.split(":")[1],
      name: item.candidate.name,
      description: "",
      source: "local",
      initParams: item.config,
    }));
  return render(
    <InstalledResourceBindingCard
      payload={{
        subtype: "installed_resource_binding",
        agent_id: 42,
        resources,
      }}
    />,
  );
}

async function choosePolicy() {
  fireEvent.click(
    screen.getByRole("button", { name: "Select knowledge bases" }),
  );
  await screen.findByRole("dialog", { name: "Knowledge selection" });
  fireEvent.click(screen.getByRole("button", { name: "Choose policy" }));
  expect(screen.getByText("Expense policy")).toBeInTheDocument();
}

beforeEach(() => {
  vi.clearAllMocks();
  mock.tools = [];
  mock.editedAgent = undefined;
  mock.knowledgeError = false;
  mock.knowledgeLoading = false;
  mock.knowledge = [
    { id: "001", index_name: "expense_index", name: "Expense policy" },
  ];
  mock.waitForIdle.mockResolvedValue(true);
  mock.apply.mockReturnValue(true);
  mock.replace.mockReturnValue(true);
  mock.searchToolConfig.mockResolvedValue({
    success: true,
    data: { params: [] },
  });
  mock.updateToolConfig.mockResolvedValue({ success: true });
  mock.saveSkillInstance.mockResolvedValue({ success: true });
  mock.searchAgentInfo.mockImplementation(async () => ({
    success: true,
    data: { tools: mock.tools, skills: [] },
  }));
});

describe("NL2A-RESOURCE-D1-001", () => {
  it("renders three resource types and preserves ordinary Tool and Skill configuration", async () => {
    const param = [{ name: "token", type: "string", required: false }];
    const { container } = show([
      resource("knowledge_base_search"),
      {
        ...resource("Web search", 2, "tool", param),
        candidate: {
          ...resource("Web search", 2).candidate,
          source: "MCP_TOOL",
        },
      },
      resource("Report skill", 3, "skill", param),
      resource("ind_aidp_search", 4),
    ]);
    expect(container.querySelectorAll("section")).toHaveLength(1);
    expect(screen.getAllByText("Knowledge").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Local").length).toBeGreaterThan(0);
    expect(screen.getByText("Skill")).toBeInTheDocument();
    expect(screen.getByText("MCP")).toBeInTheDocument();
    expect(
      screen.queryByText("Recommended", { exact: true }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Optional", { exact: true }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: "Knowledge search" }),
    ).toBeChecked();
    expect(screen.queryByText("knowledge_base_search")).not.toBeInTheDocument();
    expect(
      screen.queryByText("knowledge_base_search internal description"),
    ).not.toBeInTheDocument();
    expect(screen.getByText("ind_aidp_search")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Configure Web search" }),
    );
    await screen.findByText("Tool configuration");
    fireEvent.click(
      screen.getByRole("button", { name: "Configure Report skill" }),
    );
    expect(screen.getByText("Skill configuration")).toBeInTheDocument();
  });

  it.each(["knowledge_base_search", "aidp_search"])(
    "keeps %s selection draft isolated and saves the correct identity",
    async (name) => {
      show([resource(name)]);
      expect(screen.getByText("Knowledge search")).toBeInTheDocument();
      expect(
        screen.getByText("Knowledge", { exact: true }),
      ).toBeInTheDocument();
      expect(screen.queryByText(name, { exact: true })).not.toBeInTheDocument();
      fireEvent.click(
        screen.getByRole("button", { name: "Select knowledge bases" }),
      );
      await screen.findByRole("dialog");
      expect(
        screen.getByText(name === "aidp_search" ? "Limit: 10" : "Limit: none"),
      ).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Cancel selection" }));
      expect(mock.updateToolConfig).not.toHaveBeenCalled();
      await choosePolicy();
      expect(mock.updateToolConfig).not.toHaveBeenCalled();
      fireEvent.click(screen.getByRole("button", { name: /^Bind selected/ }));
      await waitFor(() =>
        expect(mock.updateToolConfig).toHaveBeenCalledWith(
          1,
          42,
          name === "aidp_search"
            ? { kds_list: '["001"]' }
            : { index_names: ["expense_index"] },
          true,
        ),
      );
      await waitFor(() =>
        expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled(),
      );
      fireEvent.click(screen.getByRole("button", { name: "Continue" }));
      await waitFor(() => expect(mock.append).toHaveBeenCalledTimes(1));
      expect(
        mock.append.mock.calls[0][0].metadata.custom.nl2agentCardAction.result
          .bound,
      ).toEqual([{ resource_type: "tool", resource_id: 1 }]);
      expect(mock.requestConfigFocus).toHaveBeenCalledWith(42, {
        section: "knowledge_base",
      });
    },
  );

  it("preselects an existing concrete knowledge binding and saves changes before continuing", async () => {
    const params = [
      {
        name: "index_names",
        type: "array",
        required: false,
        value: ["expense_index"],
      },
    ];
    mock.editedAgent = {
      tools: [{ id: "1", name: "knowledge_base_search", initParams: params }],
    };
    mock.searchToolConfig.mockResolvedValue({
      success: true,
      data: { params },
    });
    show([resource("knowledge_base_search")]);
    expect(screen.getByText("Expense policy")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Select knowledge bases" }),
    );
    await screen.findByRole("dialog");
    expect(screen.getByText("Selected: 001")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Choose none" }));
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /^Bind selected/ }));
    expect(mock.updateToolConfig).not.toHaveBeenCalled();
    expect(mock.append).not.toHaveBeenCalled();
  });

  it("rejects empty knowledge bindings and keeps persistence failures retryable", async () => {
    show([resource("aidp_search")]);
    fireEvent.click(screen.getByRole("button", { name: /^Bind selected/ }));
    expect(mock.updateToolConfig).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    // Validation opens the picker so the missing selection can be completed directly.
    fireEvent.click(
      await screen.findByRole("button", { name: "Choose policy" }),
    );
    mock.updateToolConfig.mockResolvedValueOnce({
      success: false,
      error: new Error("Save failed"),
    });
    fireEvent.click(screen.getByRole("button", { name: /^Bind selected/ }));
    await screen.findByText("Failed");
    expect(mock.append).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Retry failed" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled(),
    );
    expect(mock.updateToolConfig).toHaveBeenCalledTimes(2);
  });

  it("shows knowledge catalog loading and error states without exposing a tool modal", () => {
    mock.knowledgeLoading = true;
    const view = show([resource("aidp_search")]);
    expect(
      screen.getByRole("button", { name: "Select knowledge bases" }),
    ).toBeDisabled();
    view.unmount();
    mock.knowledgeLoading = false;
    mock.knowledgeError = true;
    show([resource("aidp_search")]);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Failed to load knowledge bases.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry failed" }));
    expect(mock.refetch).toHaveBeenCalledTimes(1);
    expect(mock.updateToolConfig).not.toHaveBeenCalled();
  });
  it("separates pending and bound resources with counts, highlight and collapse", async () => {
    const pending = resource("Web search", 1);
    const optional = {
      ...resource("Other search", 2),
      recommendation: "optional" as const,
    };
    const bound = resource("File reader", 8);
    mock.editedAgent = {
      tools: [{ id: "8", name: "File reader", initParams: [] }],
    };
    show([pending, optional, bound]);
    const pendingRegion = screen.getByRole("region", {
      name: "Resources to bind",
    });
    const boundRegion = screen.getByRole("region", { name: "Bound resources" });
    expect(pendingRegion).toHaveTextContent("Resources to bind 2");
    expect(pendingRegion).toHaveTextContent("Selected 1 items");
    expect(
      within(pendingRegion).queryByText("File reader"),
    ).not.toBeInTheDocument();
    expect(within(boundRegion).getByText("File reader")).toBeInTheDocument();
    expect(within(boundRegion).queryByRole("checkbox")).not.toBeInTheDocument();
    expect(
      within(boundRegion).queryByText("File reader internal description"),
    ).not.toBeInTheDocument();
    const checked = screen.getByRole("checkbox", { name: "Web search" });
    expect(checked).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: "Other search" }),
    ).not.toBeChecked();
    expect(checked.closest("[data-resource-ref]")?.className).toContain(
      "bg-blue-50/60",
    );
    fireEvent.click(checked);
    expect(pendingRegion).toHaveTextContent("Selected 0 items");
    expect(checked.closest("[data-resource-ref]")?.className).not.toContain(
      "bg-blue-50/60",
    );
    fireEvent.click(checked);
    fireEvent.click(
      within(boundRegion).getByRole("button", { expanded: true }),
    );
    expect(
      within(boundRegion).queryByText("File reader"),
    ).not.toBeInTheDocument();
    fireEvent.click(
      within(boundRegion).getByRole("button", { expanded: false }),
    );
    expect(within(boundRegion).getByText("File reader")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Bind selected (1)" }));
    await waitFor(() =>
      expect(within(boundRegion).getByText("Web search")).toBeInTheDocument(),
    );
    expect(
      within(pendingRegion).queryByText("Web search"),
    ).not.toBeInTheDocument();
    expect(pendingRegion).toHaveTextContent("Resources to bind 1");
    expect(boundRegion).toHaveTextContent("Bound resources2");
    expect(mock.updateToolConfig).toHaveBeenCalledTimes(1);
    expect(mock.append).not.toHaveBeenCalled();
  });
  it("renders concrete recommendations, preserves existing bindings and labels associated knowledge", async () => {
    const config = [
      {
        name: "index_names",
        type: "array",
        required: true,
        value: ["existing_index", "expense_index"],
      },
    ];
    const suggestion = resource("knowledge_base_search", 1, "tool", config);
    suggestion.knowledge_recommendations = [
      {
        id: "1",
        binding_value: "expense_index",
        name: "Expense policy",
        score: 0.9,
      },
    ];
    suggestion.knowledge_bound_values = ["existing_index"];
    mock.editedAgent = {
      tools: [
        {
          id: "1",
          name: "knowledge_base_search",
          initParams: [{ ...config[0], value: ["existing_index"] }],
        },
      ],
    };
    mock.knowledge.push({
      id: "existing_index",
      index_name: "existing_index",
      name: "Existing policy",
    });
    show([suggestion]);
    const pending = screen.getByRole("region", { name: "Resources to bind" });
    expect(
      within(pending).getByText("Recommended knowledge bases:"),
    ).toBeInTheDocument();
    expect(within(pending).getByText("Expense policy")).toBeInTheDocument();
    expect(
      within(pending).queryByText("Existing policy"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Bound resources" }),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Select knowledge bases" }),
    );
    await screen.findByRole("dialog");
    expect(
      screen.getByText("Selected: 001,existing_index"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel selection" }));
    expect(mock.updateToolConfig).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Bind selected (1)" }));
    await waitFor(() =>
      expect(mock.updateToolConfig).toHaveBeenCalledWith(
        1,
        42,
        { index_names: ["existing_index", "expense_index"] },
        true,
      ),
    );
    const bound = await screen.findByRole("region", {
      name: "Bound resources",
    });
    expect(
      within(bound).getByText("Associated knowledge bases:"),
    ).toBeInTheDocument();
    expect(within(bound).getByText("Expense policy")).toBeInTheDocument();
    expect(within(bound).getByText("Existing policy")).toBeInTheDocument();
    expect(mock.append).not.toHaveBeenCalled();
  });

  it("keeps the generic knowledge resource and empty recommendation manually configurable", async () => {
    const generic = resource("aidp_search");
    generic.knowledge_recommendations = [];
    show([generic]);
    expect(
      screen.getByText("Recommended knowledge bases:"),
    ).toBeInTheDocument();
    expect(screen.getByText("None")).toBeInTheDocument();
    expect(screen.getByText("Knowledge search")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Select knowledge bases" }),
    );
    await screen.findByRole("dialog");
    fireEvent.click(screen.getByRole("button", { name: "Cancel selection" }));
    expect(
      screen.getByText("Recommended knowledge bases:"),
    ).toBeInTheDocument();
    await choosePolicy();
    expect(screen.getByText("Selected knowledge bases:")).toBeInTheDocument();
    expect(
      screen.queryByText("Recommended knowledge bases:"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("None")).not.toBeInTheDocument();
    expect(mock.updateToolConfig).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /^Bind selected/ }));
    const associated = await screen.findByRole("region", {
      name: "Bound resources",
    });
    expect(
      within(associated).getByText("Associated knowledge bases:"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Selected knowledge bases:"),
    ).not.toBeInTheDocument();
    expect(mock.append).not.toHaveBeenCalled();
  });
});

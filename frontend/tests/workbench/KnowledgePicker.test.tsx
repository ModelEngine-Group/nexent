// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { beforeEach, expect, it, vi } from "vitest";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConversationKnowledgeScopeModal } from "@/app/newchat/assistant-ui/conversation-knowledge-scope-modal";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import type {
  KnowledgeCapabilities,
  ConversationKnowledgeScope,
} from "@/types/knowledgeScope";
import type { KnowledgeBase } from "@/types/knowledgeBase";

const fixtures = vi.hoisted(() => ({
  t: (key: string) => key,
  groups: { groups: [] },
  predicates: [],
  deployment: { enableAidpKnowledge: false, isDeploymentReady: true },
}));
vi.mock("@/components/providers/deploymentProvider", () => ({
  useDeployment: () => fixtures.deployment,
}));
vi.mock("react-i18next", async (original) => ({
  ...(await original<typeof import("react-i18next")>()),
  useTranslation: () => ({ t: fixtures.t, i18n: { language: "zh" } }),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: { tenantId: "tenant" } }),
}));
vi.mock("@/hooks/group/useGroupList", () => ({
  useGroupList: () => ({ data: fixtures.groups }),
}));
vi.mock("@/hooks/agent/useToolList", () => ({
  useToolList: () => ({
    isLoading: false,
    availableTools: [
      {
        name: "knowledge_base_search",
        initParams: [{ name: "top_k", type: "number", value: 5 }],
      },
      {
        name: "aidp_search",
        initParams: [{ name: "top_k", type: "number", value: 5 }],
      },
    ],
  }),
}));
vi.mock("@/features/workbench/hooks/useResourceTags", () => ({
  useResourceTags: () => ({
    definitions: [],
    predicates: fixtures.predicates,
    visibleIds: null,
  }),
}));
vi.mock("@/services/knowledgeBaseService", () => ({
  default: {
    getKnowledgeBasesInfo: vi.fn(),
    getAidpKnowledgeBasesAll: vi.fn(),
    mapAidpKnowledgeBasesToKnowledgeBases: (items: unknown[]) => items,
  },
}));

const capabilities: KnowledgeCapabilities = {
  agent_id: 7,
  version_no: 3,
  sources: {
    local: {
      enabled: true,
      max_select: 5,
      requires_same_embedding_model: true,
      default_summary: "",
      default_knowledge_ids: ["1"],
      default_range_values: [],
    },
    aidp: {
      enabled: false,
      max_select: 5,
      default_summary: "",
      default_knowledge_ids: [],
      default_range_values: [],
    },
  },
};
const selection: ConversationKnowledgeScope = {
  schema_version: 1,
  local: { mode: "override", knowledge_ids: ["1", "2"] },
  aidp: { mode: "disabled", kds_ids: [] },
};

it("AIDP conversation draft saves fixed linked candidates and cancels without mutation", async () => {
  fixtures.deployment.enableAidpKnowledge = true;
  const confirm = vi.fn();
  const saved: ConversationKnowledgeScope = {
    schema_version: 1,
    local: { mode: "disabled", knowledge_ids: [] },
    aidp: { mode: "inherit", kds_ids: [] },
    retrieval_config: { top_k: 7 },
  };
  const inherited = {
    ...capabilities,
    sources: {
      ...capabilities.sources,
      aidp: {
        ...capabilities.sources.aidp,
        enabled: true,
        default_retrieval_config: { top_k: 10, vector_candidates: 30 },
      },
    },
  };
  render(
    <ConversationKnowledgeScopeModal
      open
      presentation="drawer"
      value={saved}
      capabilities={inherited}
      onCancel={vi.fn()}
      onConfirm={confirm}
    />
  );
  await screen.findByRole("option", { name: /AIDP Catalog/ });
  await userEvent.click(
    screen.getByRole("button", {
      name: "chat.knowledgeScope.retrievalSettings",
    })
  );
  const settings = within(
    (await screen.findByText("aidpRetrieval.title")).closest<HTMLElement>(
      '[role="dialog"]'
    )!
  );
  expect(
    settings.getByRole("spinbutton", { name: "aidpRetrieval.fields.top_k" })
  ).toHaveValue(7);
  await userEvent.click(settings.getByText("aidpRetrieval.details"));
  const vectorGroup = within(
    settings.getByRole("region", {
      name: "aidpRetrieval.groups.vector_search",
    })
  );
  expect(
    vectorGroup.getByRole("spinbutton", {
      name: "aidpRetrieval.fields.initialCandidates",
    })
  ).toHaveValue(30);
  fireEvent.change(
    vectorGroup.getByRole("spinbutton", {
      name: "aidpRetrieval.fields.initialCandidates",
    }),
    { target: { value: "7" } }
  );
  fireEvent.change(
    settings.getByRole("spinbutton", { name: "aidpRetrieval.fields.top_k" }),
    { target: { value: "9" } }
  );
  expect(
    vectorGroup.getByRole("spinbutton", {
      name: "aidpRetrieval.fields.initialCandidates",
    })
  ).toHaveValue(9);
  expect(confirm).not.toHaveBeenCalled();
  await userEvent.click(
    settings.getByRole("button", { name: "common.confirm" })
  );
  expect(confirm).not.toHaveBeenCalled();
  await userEvent.click(
    screen.getByRole("button", { name: "workbench.controls.confirm" })
  );
  expect(confirm.mock.calls[0][0].retrieval_config).toEqual({
    top_k: 9,
    vector_candidates: 9,
  });
  expect(saved.retrieval_config).toEqual({ top_k: 7 });
});
beforeEach(() => {
  vi.clearAllMocks();
  fixtures.deployment.enableAidpKnowledge = false;
  fixtures.deployment.isDeploymentReady = true;
  vi.mocked(knowledgeBaseService.getAidpKnowledgeBasesAll).mockResolvedValue({
    value: [{ id: "aidp-1", name: "AIDP Catalog", permission: "READ_ONLY" }],
  } as unknown as Awaited<
    ReturnType<typeof knowledgeBaseService.getAidpKnowledgeBasesAll>
  >);
  vi.mocked(knowledgeBaseService.getKnowledgeBasesInfo).mockResolvedValue({
    knowledgeBases: [
      {
        id: "index-a",
        knowledge_id: 1,
        name: "Alpha",
        embeddingModel: "model-a",
        permission: "READ_ONLY",
        documentCount: 2,
      },
      {
        id: "index-b",
        knowledge_id: 2,
        name: "Beta",
        embeddingModel: "model-a",
        permission: "EDIT",
        documentCount: 3,
      },
      {
        id: "index-c",
        knowledge_id: 3,
        name: "Incompatible",
        embeddingModel: "model-b",
        permission: "READ_ONLY",
        documentCount: 1,
      },
    ] as KnowledgeBase[],
  });
});
it.each([
  null,
  capabilities,
  {
    ...capabilities,
    sources: {
      ...capabilities.sources,
      aidp: { ...capabilities.sources.aidp, enabled: true },
    },
  },
])(
  "AIDP deployment source overrides absent, local or mixed agent capabilities",
  async (agentCapabilities) => {
    fixtures.deployment.enableAidpKnowledge = true;
    const confirm = vi.fn();
    render(
      <ConversationKnowledgeScopeModal
        open
        value={selection}
        capabilities={agentCapabilities}
        onCancel={vi.fn()}
        onConfirm={confirm}
      />
    );
    await userEvent.click(
      await screen.findByRole("option", { name: /AIDP Catalog/ })
    );
    expect(knowledgeBaseService.getKnowledgeBasesInfo).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("option", { name: /Alpha/ })
    ).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "chat.knowledgeScope.confirm" })
    );
    expect(confirm.mock.calls[0][0]).toEqual({
      schema_version: 1,
      local: { mode: "disabled", knowledge_ids: [] },
      aidp: { mode: "override", kds_ids: ["aidp-1"] },
    });
  }
);

it("waits for deployment settings and uses local catalog without an agent", async () => {
  fixtures.deployment.isDeploymentReady = false;
  const props = {
    open: true,
    value: null,
    capabilities: null,
    onCancel: vi.fn(),
    onConfirm: vi.fn(),
  };
  const { rerender } = render(<ConversationKnowledgeScopeModal {...props} />);
  expect(knowledgeBaseService.getKnowledgeBasesInfo).not.toHaveBeenCalled();
  expect(knowledgeBaseService.getAidpKnowledgeBasesAll).not.toHaveBeenCalled();
  fixtures.deployment.isDeploymentReady = true;
  rerender(<ConversationKnowledgeScopeModal {...props} />);
  await screen.findByRole("option", { name: /Alpha/ });
  expect(knowledgeBaseService.getAidpKnowledgeBasesAll).not.toHaveBeenCalled();
});

it.each(["modal", "drawer"] as const)(
  "%s knowledge selection preserves retrieval configuration on confirmation",
  async (presentation) => {
    const confirm = vi.fn();
    const configuredSelection = {
      ...selection,
      retrieval_config: { top_k: 8 },
    };
    render(
      <ConversationKnowledgeScopeModal
        open
        presentation={presentation}
        value={configuredSelection}
        capabilities={capabilities}
        onCancel={vi.fn()}
        onConfirm={confirm}
      />
    );
    await screen.findByRole("option", { name: /Alpha/ });
    await userEvent.click(screen.getByRole("option", { name: /Alpha/ }));
    await userEvent.click(
      screen.getByRole("button", {
        name: "chat.knowledgeScope.retrievalSettings",
      })
    );
    const dialog = (
      await screen.findByText("agent.knowledge.configModal.title")
    ).closest<HTMLElement>('[role="dialog"]')!;
    const input = within(dialog).getByRole("spinbutton");
    await userEvent.tripleClick(input);
    await userEvent.keyboard("8");
    await userEvent.click(
      within(dialog).getByRole("button", { name: "common.confirm" })
    );
    expect(confirm).not.toHaveBeenCalled();
    await userEvent.click(
      screen.getByRole("button", {
        name:
          presentation === "drawer"
            ? "workbench.controls.confirm"
            : "chat.knowledgeScope.confirm",
      })
    );
    expect(confirm.mock.calls[0][0].retrieval_config).toEqual({ top_k: 8 });
    expect(confirm.mock.calls[0][0].local.knowledge_ids).toEqual(["2"]);
    expect(configuredSelection.local.knowledge_ids).toEqual(["1", "2"]);
    expect(configuredSelection.retrieval_config).toEqual({ top_k: 8 });
  }
);

it("discarding retrieval edits and canceling the drawer restores the saved draft on reopening", async () => {
  const configuredSelection = { ...selection, retrieval_config: { top_k: 6 } };
  const confirm = vi.fn(),
    cancel = vi.fn();
  const props = {
    presentation: "drawer" as const,
    value: configuredSelection,
    capabilities,
    onConfirm: confirm,
    onCancel: cancel,
  };
  const view = render(<ConversationKnowledgeScopeModal {...props} open />);
  await screen.findByRole("option", { name: /Alpha/ });
  const openSettings = async () => {
    await userEvent.click(
      screen.getByRole("button", {
        name: "chat.knowledgeScope.retrievalSettings",
      })
    );
    return within(
      (
        await screen.findByText("agent.knowledge.configModal.title")
      ).closest<HTMLElement>('[role="dialog"]')!
    );
  };
  let settings = await openSettings();
  await userEvent.tripleClick(settings.getByRole("spinbutton"));
  await userEvent.keyboard("8");
  await userEvent.click(
    settings.getByRole("button", { name: "common.cancel" })
  );
  settings = await openSettings();
  expect(settings.getByRole("spinbutton")).toHaveValue("6");
  await userEvent.tripleClick(settings.getByRole("spinbutton"));
  await userEvent.keyboard("9");
  await userEvent.click(
    settings.getByRole("button", { name: "common.confirm" })
  );
  await userEvent.click(screen.getByRole("button", { name: "common.cancel" }));
  expect(cancel).toHaveBeenCalledOnce();
  expect(confirm).not.toHaveBeenCalled();
  view.rerender(<ConversationKnowledgeScopeModal {...props} open={false} />);
  view.rerender(<ConversationKnowledgeScopeModal {...props} open />);
  await screen.findByRole("option", { name: /Alpha/ });
  settings = await openSettings();
  expect(settings.getByRole("spinbutton")).toHaveValue("6");
  expect(configuredSelection.retrieval_config).toEqual({ top_k: 6 });
});

it("retains retrieval and knowledge drafts after a failed drawer save and permits retry", async () => {
  const configuredSelection = { ...selection, retrieval_config: { top_k: 6 } };
  const confirm = vi
    .fn()
    .mockRejectedValueOnce(new Error("save unavailable"))
    .mockResolvedValueOnce(undefined);
  render(
    <ConversationKnowledgeScopeModal
      open
      presentation="drawer"
      value={configuredSelection}
      capabilities={capabilities}
      onCancel={vi.fn()}
      onConfirm={confirm}
    />
  );
  await screen.findByRole("option", { name: /Alpha/ });
  await userEvent.click(
    screen.getByRole("button", {
      name: "chat.knowledgeScope.retrievalSettings",
    })
  );
  const settings = within(
    (
      await screen.findByText("agent.knowledge.configModal.title")
    ).closest<HTMLElement>('[role="dialog"]')!
  );
  await userEvent.tripleClick(settings.getByRole("spinbutton"));
  await userEvent.keyboard("8");
  await userEvent.click(
    settings.getByRole("button", { name: "common.confirm" })
  );
  expect(confirm).not.toHaveBeenCalled();
  await userEvent.click(
    screen.getByRole("button", { name: "workbench.controls.confirm" })
  );
  await waitFor(() => expect(confirm).toHaveBeenCalledOnce());
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "workbench.controls.confirm" })
    ).toBeEnabled()
  );
  await userEvent.click(
    screen.getByRole("button", { name: "workbench.controls.confirm" })
  );
  await waitFor(() => expect(confirm).toHaveBeenCalledTimes(2));
  expect(confirm.mock.calls[1][0].retrieval_config).toEqual({ top_k: 8 });
  expect(confirm.mock.calls[1][0].local.knowledge_ids).toEqual(["1", "2"]);
  expect(configuredSelection.retrieval_config).toEqual({ top_k: 6 });
});

it("UT-FE-WB-025 uses one authorized catalog and disables incompatible embeddings", async () => {
  render(
    <ConversationKnowledgeScopeModal
      open
      value={selection}
      capabilities={capabilities}
      onCancel={vi.fn()}
      onConfirm={vi.fn()}
    />
  );
  expect(await screen.findByRole("option", { name: /Alpha/ })).toHaveAttribute(
    "aria-selected",
    "true"
  );
  expect(screen.getByRole("option", { name: /Incompatible/ })).toBeDisabled();
  expect(screen.queryByRole("tab", { name: "我的" })).not.toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: "仓库" })).not.toBeInTheDocument();
  expect(knowledgeBaseService.getAidpKnowledgeBasesAll).not.toHaveBeenCalled();
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(
    screen.queryByText("chat.knowledgeScope.localTab")
  ).not.toBeInTheDocument();
  expect(
    screen.queryByText("knowledgeBase.selected.prefix")
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "移除 Alpha" })
  ).toBeInTheDocument();
});
it("UT-FE-WB-026 deselecting filtered results preserves hidden selections", async () => {
  const confirm = vi.fn();
  render(
    <ConversationKnowledgeScopeModal
      open
      value={selection}
      capabilities={capabilities}
      onCancel={vi.fn()}
      onConfirm={confirm}
    />
  );
  await screen.findByRole("option", { name: /Alpha/ });
  await userEvent.type(
    screen.getByRole("searchbox", { name: "搜索知识库" }),
    "Alpha"
  );
  await userEvent.click(screen.getByRole("button", { name: "取消全选" }));
  await userEvent.click(
    screen.getByRole("button", { name: "chat.knowledgeScope.confirm" })
  );
  expect(confirm.mock.calls[0][0].local).toEqual({
    mode: "override",
    knowledge_ids: ["2"],
  });
});
it("UT-FE-WB-027 restores defaults without inserting unrelated knowledge bases", async () => {
  const confirm = vi.fn();
  render(
    <ConversationKnowledgeScopeModal
      open
      value={selection}
      capabilities={capabilities}
      onCancel={vi.fn()}
      onConfirm={confirm}
    />
  );
  await screen.findByRole("option", { name: /Alpha/ });
  await userEvent.click(
    screen.getByRole("button", { name: "chat.knowledgeScope.restoreDefault" })
  );
  expect(screen.getByRole("option", { name: /Beta/ })).toHaveAttribute(
    "aria-selected",
    "false"
  );
  await userEvent.click(
    screen.getByRole("button", { name: "chat.knowledgeScope.confirm" })
  );
  expect(confirm.mock.calls[0][0].local).toEqual({
    mode: "inherit",
    knowledge_ids: [],
  });
});
it("failed catalog loading cannot be confirmed as an empty replacement", async () => {
  vi.mocked(knowledgeBaseService.getKnowledgeBasesInfo).mockRejectedValue(
    new Error("unavailable")
  );
  const confirm = vi.fn();
  render(
    <ConversationKnowledgeScopeModal
      open
      value={selection}
      capabilities={capabilities}
      onCancel={vi.fn()}
      onConfirm={confirm}
    />
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "chat.knowledgeScope.confirm" })
    ).toBeDisabled()
  );
  expect(confirm).not.toHaveBeenCalled();
});

it("reopening knowledge selection ignores the unfinished catalog from the previous session", async () => {
  type Result = Awaited<
    ReturnType<typeof knowledgeBaseService.getKnowledgeBasesInfo>
  >;
  let finishOld!: (result: Result) => void;
  vi.mocked(knowledgeBaseService.getKnowledgeBasesInfo).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finishOld = resolve;
      })
  );
  const props = {
    value: null,
    capabilities: null,
    onCancel: vi.fn(),
    onConfirm: vi.fn(),
  };
  const { rerender } = render(
    <ConversationKnowledgeScopeModal {...props} open />
  );
  expect(
    screen.getByRole("button", { name: "chat.knowledgeScope.confirm" })
  ).toBeDisabled();
  rerender(<ConversationKnowledgeScopeModal {...props} open={false} />);
  rerender(<ConversationKnowledgeScopeModal {...props} open />);
  await screen.findByRole("option", { name: /Alpha/ });
  await act(async () => {
    finishOld({
      knowledgeBases: [
        {
          id: "outdated",
          knowledge_id: 99,
          name: "Outdated catalog",
          permission: "READ_ONLY",
        },
      ],
    } as Result);
  });
  expect(
    screen.queryByRole("option", { name: /Outdated catalog/ })
  ).not.toBeInTheDocument();
  expect(screen.getByRole("option", { name: /Alpha/ })).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "chat.knowledgeScope.confirm" })
  ).toBeEnabled();
});

it("uses text-only knowledge rows in the Workbench drawer and preserves cancellation", async () => {
  const cancel = vi.fn(),
    confirm = vi.fn();
  vi.mocked(knowledgeBaseService.getKnowledgeBasesInfo).mockResolvedValue({
    knowledgeBases: [
      {
        id: "index-a",
        knowledge_id: 1,
        name: "Alpha",
        description: "Knowledge details",
        tags: ["Finance"],
        embeddingModel: "model-a",
        permission: "READ_ONLY",
        documentCount: 2,
      },
    ] as KnowledgeBase[],
  });
  render(
    <ConversationKnowledgeScopeModal
      open
      presentation="drawer"
      value={selection}
      capabilities={capabilities}
      onCancel={cancel}
      onConfirm={confirm}
    />
  );
  const row = await screen.findByRole("option", { name: "Alpha" });
  expect(row).toHaveTextContent("Knowledge details");
  expect(row).toHaveTextContent("Finance");
  expect(row.querySelector(".lucide-book-open")).toBeNull();
  expect(row).not.toHaveTextContent("READ_ONLY");
  expect(row).not.toHaveTextContent("model-a");
  expect(
    screen.queryByRole("button", { name: "编辑" })
  ).not.toBeInTheDocument();
  await userEvent.click(row);
  expect(row).toHaveAttribute("aria-selected", "false");
  await userEvent.click(screen.getByRole("button", { name: "common.cancel" }));
  expect(cancel).toHaveBeenCalledOnce();
  expect(confirm).not.toHaveBeenCalled();
});

// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { beforeEach, expect, it, vi } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";
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
beforeEach(() => {
  vi.clearAllMocks();
  fixtures.deployment.enableAidpKnowledge = false;
  fixtures.deployment.isDeploymentReady = true;
  vi.mocked(knowledgeBaseService.getAidpKnowledgeBasesAll).mockResolvedValue({
    value: [
      {
        id: "aidp-1",
        name: "AIDP Catalog",
        permission: "READ_ONLY",
        documentCount: 9,
        chunkCount: 27,
      },
    ],
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
it.each(
  [
    null,
    capabilities,
    {
      ...capabilities,
      sources: {
        ...capabilities.sources,
        aidp: { ...capabilities.sources.aidp, enabled: true },
      },
    },
  ].flatMap((agentCapabilities) =>
    (["modal", "drawer"] as const).map((presentation) => ({
      agentCapabilities,
      presentation,
    }))
  )
)(
  "AIDP $presentation source overrides absent, local or mixed capabilities",
  async ({ agentCapabilities, presentation }) => {
    fixtures.deployment.enableAidpKnowledge = true;
    const confirm = vi.fn();
    render(
      <ConversationKnowledgeScopeModal
        open
        presentation={presentation}
        value={selection}
        capabilities={agentCapabilities}
        onCancel={vi.fn()}
        onConfirm={confirm}
      />
    );
    const row = await screen.findByRole("option", { name: /AIDP Catalog/ });
    const item = presentation === "modal" ? row.parentElement : row;
    expect(item).not.toHaveTextContent("resourcePicker.knowledge.documents");
    expect(item).not.toHaveTextContent("resourcePicker.knowledge.chunks");
    expect(item).not.toHaveTextContent("knowledgeBase.document");
    await userEvent.click(row);
    expect(knowledgeBaseService.getKnowledgeBasesInfo).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("option", { name: /Alpha/ })
    ).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", {
        name:
          presentation === "drawer"
            ? "resourcePicker.confirm"
            : "chat.knowledgeScope.confirm",
      })
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
  const row = await screen.findByRole("option", { name: /Alpha/ });
  expect(row.parentElement).toHaveTextContent("2 knowledgeBase.document");
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
    if (presentation === "modal") {
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
    } else {
      expect(
        screen.queryByRole("button", {
          name: "chat.knowledgeScope.retrievalSettings",
        })
      ).not.toBeInTheDocument();
    }
    expect(confirm).not.toHaveBeenCalled();
    await userEvent.click(
      screen.getByRole("button", {
        name:
          presentation === "drawer"
            ? "resourcePicker.confirm"
            : "chat.knowledgeScope.confirm",
      })
    );
    expect(confirm.mock.calls[0][0].retrieval_config).toEqual({ top_k: 8 });
    expect(confirm.mock.calls[0][0].local.knowledge_ids).toEqual(["2"]);
    expect(configuredSelection.local.knowledge_ids).toEqual(["1", "2"]);
    expect(configuredSelection.retrieval_config).toEqual({ top_k: 8 });
  }
);

it("closing the drawer discards knowledge edits and preserves saved retrieval on reopening", async () => {
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
  await userEvent.click(await screen.findByRole("option", { name: "Alpha" }));
  expect(screen.getByRole("option", { name: "Alpha" })).toHaveAttribute(
    "aria-selected",
    "false"
  );
  await userEvent.click(
    screen.getByText("resourcePicker.close", { selector: "button" })
  );
  expect(cancel).toHaveBeenCalledOnce();
  expect(confirm).not.toHaveBeenCalled();
  view.rerender(<ConversationKnowledgeScopeModal {...props} open={false} />);
  view.rerender(<ConversationKnowledgeScopeModal {...props} open />);
  expect(await screen.findByRole("option", { name: "Alpha" })).toHaveAttribute(
    "aria-selected",
    "true"
  );
  await userEvent.click(
    screen.getByRole("button", { name: "resourcePicker.confirm" })
  );
  await waitFor(() => expect(confirm).toHaveBeenCalledOnce());
  expect(confirm.mock.calls[0][0].retrieval_config).toEqual({ top_k: 6 });
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
  await userEvent.click(screen.getByRole("option", { name: "Alpha" }));
  expect(confirm).not.toHaveBeenCalled();
  await userEvent.click(
    screen.getByRole("button", { name: "resourcePicker.confirm" })
  );
  await waitFor(() => expect(confirm).toHaveBeenCalledOnce());
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "resourcePicker.confirm" })
    ).toBeEnabled()
  );
  await userEvent.click(
    screen.getByRole("button", { name: "resourcePicker.confirm" })
  );
  await waitFor(() => expect(confirm).toHaveBeenCalledTimes(2));
  expect(confirm.mock.calls[1][0].retrieval_config).toEqual({ top_k: 6 });
  expect(confirm.mock.calls[1][0].local.knowledge_ids).toEqual(["2"]);
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
  expect(row).toHaveTextContent("model-a");
  expect(row).toHaveTextContent("resourcePicker.knowledge.documents");
  expect(
    screen.queryByRole("button", { name: "管理标签" })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "编辑" })
  ).not.toBeInTheDocument();
  await userEvent.click(row);
  expect(row).toHaveAttribute("aria-selected", "false");
  await userEvent.click(
    screen.getByText("resourcePicker.close", { selector: "button" })
  );
  expect(cancel).toHaveBeenCalledOnce();
  expect(confirm).not.toHaveBeenCalled();
});

it("AIDP drawer preserves its saved scope after catalog failure and hides management", async () => {
  fixtures.deployment.enableAidpKnowledge = true;
  vi.mocked(knowledgeBaseService.getAidpKnowledgeBasesAll).mockRejectedValue(
    new Error("AIDP unavailable")
  );
  const confirm = vi.fn();
  render(
    <ConversationKnowledgeScopeModal
      open
      presentation="drawer"
      value={{
        schema_version: 1,
        local: { mode: "disabled", knowledge_ids: [] },
        aidp: { mode: "override", kds_ids: ["kds:kept"] },
      }}
      capabilities={null}
      onCancel={vi.fn()}
      onConfirm={confirm}
    />
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "resourcePicker.confirm" })
    ).toBeDisabled()
  );
  expect(knowledgeBaseService.getKnowledgeBasesInfo).not.toHaveBeenCalled();
  expect(
    screen.queryByRole("button", { name: "管理标签" })
  ).not.toBeInTheDocument();
  expect(confirm).not.toHaveBeenCalled();
});

it.each([false, true])(
  "shared knowledge refresh preserves unsaved choices/search and retries errors (AIDP=%s)",
  async (aidp) => {
    fixtures.deployment.enableAidpKnowledge = aidp;
    const rows = [
      {
        id: aidp ? "kds:alpha" : "idx-alpha",
        knowledge_id: 1,
        name: "Alpha",
        permission: "READ_ONLY",
        documentCount: 2,
        embeddingModel: "a",
      },
      {
        id: aidp ? "kds:beta" : "idx-beta",
        knowledge_id: 2,
        name: "Beta",
        permission: "READ_ONLY",
        documentCount: 2,
        embeddingModel: "a",
      },
    ] as KnowledgeBase[];
    const localCatalog = vi.mocked(knowledgeBaseService.getKnowledgeBasesInfo);
    const aidpCatalog = vi.mocked(
      knowledgeBaseService.getAidpKnowledgeBasesAll
    );
    localCatalog.mockResolvedValue({ knowledgeBases: rows } as Awaited<
      ReturnType<typeof knowledgeBaseService.getKnowledgeBasesInfo>
    >);
    aidpCatalog.mockResolvedValue({ value: rows } as unknown as Awaited<
      ReturnType<typeof knowledgeBaseService.getAidpKnowledgeBasesAll>
    >);
    const confirm = vi.fn();
    render(
      <ConversationKnowledgeScopeModal
        open
        presentation="drawer"
        capabilities={null}
        value={{
          schema_version: 1,
          local: {
            mode: aidp ? "disabled" : "override",
            knowledge_ids: aidp ? [] : ["1", "2"],
          },
          aidp: {
            mode: aidp ? "override" : "disabled",
            kds_ids: aidp ? ["kds:alpha", "kds:beta"] : [],
          },
        }}
        onConfirm={confirm}
        onCancel={vi.fn()}
      />
    );
    const alpha = await screen.findByRole("option", { name: "Alpha" });
    await userEvent.click(screen.getByRole("option", { name: "Beta" }));
    expect(alpha).toHaveAttribute("aria-selected", "true");
    expect(
      screen.getByRole("checkbox", { name: "resourcePicker.selectAll" })
    ).toHaveAttribute("aria-checked", "mixed");
    const search = screen.getByRole("searchbox");
    await userEvent.type(search, "Alpha");
    if (aidp)
      aidpCatalog.mockRejectedValueOnce(new Error("catalog unavailable"));
    else localCatalog.mockRejectedValueOnce(new Error("catalog unavailable"));
    await userEvent.click(
      screen.getByRole("button", { name: "resourcePicker.refresh" })
    );
    await within(screen.getByRole("dialog")).findByText(
      "chat.knowledgeScope.listLoadFailed"
    );
    expect(
      screen.getByRole("button", { name: "resourcePicker.confirm" })
    ).toBeDisabled();
    expect(screen.getByRole("option", { name: "Alpha" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
    expect(search).toHaveValue("Alpha");
    await userEvent.click(
      screen.getByRole("button", { name: "resourcePicker.refresh" })
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "resourcePicker.confirm" })
      ).toBeEnabled()
    );
    expect(search).toHaveValue("Alpha");
    await userEvent.clear(search);
    expect(screen.getByRole("option", { name: "Beta" })).toHaveAttribute(
      "aria-selected",
      "false"
    );
    expect(confirm).not.toHaveBeenCalled();
    await userEvent.click(
      screen.getByRole("button", { name: "resourcePicker.confirm" })
    );
    await waitFor(() => expect(confirm).toHaveBeenCalledOnce());
    const scope = confirm.mock.calls[0][0];
    expect(aidp ? scope.aidp.kds_ids : scope.local.knowledge_ids).toEqual([
      aidp ? "kds:alpha" : "1",
    ]);
    expect((aidp ? aidpCatalog : localCatalog).mock.calls).toHaveLength(3);
  }
);

it("Workbench knowledge footer has only shared Close/Confirm and preserves existing retrieval configuration", async () => {
  const confirm = vi.fn();
  render(
    <ConversationKnowledgeScopeModal
      open
      presentation="drawer"
      value={{ ...selection, retrieval_config: { top_k: 6 } }}
      capabilities={capabilities}
      onCancel={vi.fn()}
      onConfirm={confirm}
    />
  );
  await screen.findByRole("option", { name: "Alpha" });
  const footer = document.querySelector(
    '[data-picker-part="footer"]'
  ) as HTMLElement;
  expect(
    within(footer)
      .getAllByRole("button")
      .map((button) => button.textContent)
  ).toEqual(["resourcePicker.close", "resourcePicker.confirm"]);
  expect(
    screen.queryByRole("button", {
      name: "chat.knowledgeScope.retrievalSettings",
    })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "chat.knowledgeScope.restoreDefault" })
  ).not.toBeInTheDocument();
  await userEvent.click(
    within(footer).getByRole("button", { name: "resourcePicker.confirm" })
  );
  await waitFor(() => expect(confirm).toHaveBeenCalledOnce());
  expect(confirm.mock.calls[0][0].retrieval_config).toEqual({ top_k: 6 });
});

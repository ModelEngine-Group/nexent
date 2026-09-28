import { beforeEach, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
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

it("retrieval configuration is a draft until outer confirmation", async () => {
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
  await userEvent.click(screen.getByRole("button", { name: /配.*置/ }));
  const dialog = (
    await screen.findByText("agent.knowledge.configModal.title")
  ).closest<HTMLElement>('[role="dialog"]')!;
  const input = within(dialog).getByRole("spinbutton");
  await userEvent.clear(input);
  await userEvent.type(input, "8");
  await userEvent.click(within(dialog).getByRole("button", { name: /确.*定/ }));
  expect(confirm).not.toHaveBeenCalled();
  await userEvent.click(
    screen.getByRole("button", { name: "chat.knowledgeScope.confirm" })
  );
  expect(confirm.mock.calls[0][0].retrieval_config).toEqual({ top_k: 8 });
  expect(selection.retrieval_config).toBeUndefined();
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

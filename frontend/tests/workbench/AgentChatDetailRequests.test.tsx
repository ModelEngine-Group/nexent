// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, render, waitFor } from "@testing-library/react";
import { StrictMode, type ComponentProps } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { AssistantRuntime } from "@assistant-ui/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Home from "@/app/newchat/page";
import { conversationService } from "@/services/conversationService";
import type { ApiConversationDetail } from "@/types/conversation";

const fixture = vi.hoisted(() => ({
  user: { id: "user", tenantId: "tenant" },
  router: { replace: vi.fn() },
  agents: [{ id: "7", agent_id: 7, name: "Analyst", current_version_no: 3 }],
}));
let runtime: AssistantRuntime;
let chat: ComponentProps<typeof import("@/app/newchat/assistant-ui/chat").Chat>;
const clients: QueryClient[] = [];

vi.mock("@assistant-ui/react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@assistant-ui/react")>();
  return {
    ...actual,
    useRemoteThreadListRuntime: (
      options: Parameters<typeof actual.useRemoteThreadListRuntime>[0]
    ) => {
      runtime = actual.useRemoteThreadListRuntime(options);
      return runtime;
    },
  };
});

vi.mock("next/navigation", () => ({
  useRouter: () => fixture.router,
  useParams: () => ({ locale: "zh" }),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: fixture.user }),
}));
vi.mock("@/components/providers/deploymentProvider", () => ({
  useDeployment: () => ({ enableAidpKnowledge: false }),
}));
vi.mock("@/hooks/agent/usePublishedAgentList", () => ({
  usePublishedAgentList: () => ({
    agents: fixture.agents,
    availableMainAgents: fixture.agents,
    isLoading: false,
  }),
}));
vi.mock("@/hooks/chat/useComposerResources", () => ({
  useComposerKnowledgeBases: () => ({ dataUpdatedAt: 0 }),
}));
vi.mock("@/hooks/chat/useConversationAgentHistory", () => ({
  useConversationAgentHistory: () => ({ data: [] }),
}));
vi.mock("@/hooks/useConfig", () => ({ useConfig: () => ({}) }));
vi.mock(
  "@/app/newchat/adapter/remote-chat-model-adapter",
  async (importOriginal) => ({
    ...(await importOriginal<object>()),
    remoteChatModelAdapter: { run: vi.fn(async function* () {}) },
  })
);
vi.mock("@/app/newchat/adapter/attachment-adapter", () => ({
  createNewChatAttachmentAdapter: () => undefined,
}));
vi.mock("@/app/newchat/assistant-ui/composer-tools", () => ({
  ComposerAttachment: () => null,
  ComposerDictation: () => null,
}));
vi.mock("@/app/newchat/assistant-ui/threadlist-sidebar", () => ({
  ThreadListSidebar: () => null,
}));
vi.mock("@/app/newchat/assistant-ui/chat", () => ({
  Chat: (props: typeof chat) => {
    chat = props;
    return null;
  },
}));

function detail(id: string): ApiConversationDetail {
  return {
    conversation_id: id,
    conversation_title: `Saved ${id}`,
    agent_id: 7,
    create_time: 0,
    runtime_metadata: { key: id },
    runtime_metadata_version: 4,
    knowledge_scope: {
      schema_version: 1,
      local: { mode: "override", knowledge_ids: [id] },
      aidp: { mode: "inherit", kds_ids: [] },
    },
    message: [
      { role: "user", message_id: Number(id), message: `Question ${id}` },
    ],
  };
}

function mount(client = new QueryClient()) {
  clients.push(client);
  return render(
    <QueryClientProvider client={client}>
      <StrictMode>
        <Home />
      </StrictMode>
    </QueryClientProvider>
  );
}
async function restored(id: string) {
  await waitFor(() => {
    expect(chat.conversationId).toBe(Number(id));
    expect(chat.runtimeMetadata).toEqual({ key: id });
    expect(chat.knowledgeScope?.local.knowledge_ids).toEqual([id]);
    expect(chat.selectedAgent?.id).toBe("7");
    expect(runtime.thread.getState().messages[0]?.content).toEqual([
      { type: "text", text: `Question ${id}` },
    ]);
  });
}

beforeEach(() => {
  window.history.replaceState({}, "", "/zh/newchat?conversation_id=42");
  sessionStorage.clear();
  fixture.user = { id: "user", tenantId: "tenant" };
  vi.spyOn(conversationService, "getById").mockImplementation(async (id) =>
    detail(id)
  );
  vi.spyOn(conversationService, "getDetail").mockImplementation(async (id) => ({
    code: 0,
    data: [detail(String(id))],
    message: "ok",
  }));
  vi.spyOn(conversationService, "getList").mockResolvedValue({
    items: [42, 43].map((id) => ({
      conversation_id: id,
      agent_id: 7,
      conversation_title: `Saved ${id}`,
      create_time: 0,
      update_time: 0,
    })),
    metadata: { total: 2, today: 0, last_7_days: 0, older: 2 },
  });
  vi.spyOn(conversationService, "getWorkbenchPins").mockResolvedValue({
    items: [],
  });
  vi.spyOn(conversationService, "getKnowledgeCapabilities").mockResolvedValue(
    null as never
  );
});
afterEach(() => clients.splice(0).forEach((client) => client.clear()));

it("shares route, actual history, metadata, scope and late resume reads per Agent-chat activation", async () => {
  const client = new QueryClient();
  const first = mount(client);
  await restored("42");
  expect(conversationService.getById).toHaveBeenCalledExactlyOnceWith("42");
  expect(conversationService.getDetail).not.toHaveBeenCalled();
  await act(async () => {
    await runtime.threads.switchToThread("43");
  });
  await restored("43");
  await act(async () => {
    await runtime.threads.switchToThread("42");
  });
  await restored("42");
  expect(
    vi.mocked(conversationService.getById).mock.calls.map(([id]) => id)
  ).toEqual(["42", "43", "42"]);
  await act(async () => {
    await runtime.threads.switchToThread("42");
  });
  expect(conversationService.getById).toHaveBeenCalledTimes(3);
  first.unmount();
  mount(client);
  await restored("42");
  expect(conversationService.getById).toHaveBeenCalledTimes(4);
  expect(fixture.router.replace).not.toHaveBeenCalled();
});

it("refreshes visibility and invalidates a saved knowledge change before later restoration", async () => {
  const get = vi.mocked(conversationService.getById);
  const client = new QueryClient();
  mount(client);
  await restored("42");
  const before = get.mock.calls.length;
  vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
  await act(async () => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
  expect(get).toHaveBeenCalledTimes(before + 1);
  const snapshots = () =>
    client
      .getQueryCache()
      .getAll()
      .filter((query) => query.queryKey[0] === "workbench-conversation-detail");
  expect(snapshots()).toHaveLength(1);
  vi.spyOn(conversationService, "updateKnowledgeScope").mockResolvedValue({
    effective_preview: null,
    warnings: [],
  } as never);
  await act(async () => {
    await chat.onKnowledgeScopeChange?.(null);
  });
  expect(conversationService.updateKnowledgeScope).toHaveBeenCalledWith(
    42,
    null
  );
  expect(get).toHaveBeenCalledTimes(before + 1);
  expect(snapshots()).toHaveLength(0);
});

it("isolates restored snapshots when the authenticated scope changes", async () => {
  const client = new QueryClient();
  const view = mount(client);
  await restored("42");
  fixture.user = { id: "other", tenantId: "other-tenant" };
  view.rerender(
    <QueryClientProvider client={client}>
      <StrictMode>
        <Home />
      </StrictMode>
    </QueryClientProvider>
  );
  await waitFor(() =>
    expect(conversationService.getById).toHaveBeenCalledTimes(2)
  );
  await restored("42");
  view.unmount();
  await act(async () => {});
  expect(
    client
      .getQueryCache()
      .getAll()
      .filter((query) => query.queryKey[0] === "workbench-conversation-detail")
  ).toHaveLength(0);
});

it("restores changed server knowledge instead of the old per-thread scope on re-entry", async () => {
  mount();
  await restored("42");
  await act(async () => {
    await runtime.threads.switchToThread("43");
  });
  await restored("43");
  const fresh = detail("42");
  fresh.knowledge_scope!.local.knowledge_ids = ["fresh-server-scope"];
  vi.mocked(conversationService.getById).mockResolvedValue(fresh);
  await act(async () => {
    await runtime.threads.switchToThread("42");
  });
  await waitFor(() =>
    expect(chat.knowledgeScope?.local.knowledge_ids).toEqual([
      "fresh-server-scope",
    ])
  );
  expect(chat.runtimeMetadata).toEqual({ key: "42" });
});

it("shares a failed detail read and retries after a page remount", async () => {
  const get = vi
    .mocked(conversationService.getById)
    .mockRejectedValue(new Error("offline"));
  const view = mount();
  await waitFor(() => expect(get).toHaveBeenCalledTimes(1));
  await act(async () => {});
  expect(get).toHaveBeenCalledTimes(1);
  expect(conversationService.getDetail).not.toHaveBeenCalled();
  view.unmount();
  get.mockImplementation(async (id) => detail(id));
  mount();
  await restored("42");
  expect(get).toHaveBeenCalledTimes(2);
});

// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { screen, waitFor } from "@testing-library/dom";
import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import WorkbenchPage from "@/features/workbench/WorkbenchPage";

const switchToNewThread = vi.fn();
const reloadThreads = vi.fn();
const initializeThread = vi.fn();
const updateThreadCustom = vi.fn();
const setRunConfig = vi.fn();

const runtimeMock = {
  threads: {
    switchToNewThread,
    reload: reloadThreads,
    getItemById: vi.fn(),
    getState: vi.fn(),
  },
  thread: {
    composer: { setRunConfig },
    getState: vi.fn(),
  },
};

let auiStateCalls = 0;
let auiStateLogged = 0;

let runtimeState = {
  threads: {
    mainThreadId: "thread-1",
    isLoading: false,
    threadItems: [{ id: "thread-1" }] as Array<{
      id: string;
      remoteId?: string;
    }>,
  },
  thread: { isLoading: false, isRunning: false },
};

const publishedAgentListValue = vi.hoisted(() => ({
  usePublishedAgentListValue: {
    isLoading: false,
    agents: [
      {
        id: "41",
        agent_id: 41,
        name: "workbench_agent",
        display_name: "Workbench Agent",
        current_version_no: 1,
      },
    ],
  },
}));

const nl2AgentFlowValue = vi.hoisted(() => ({
  resetFlow: vi.fn(),
  markGenerationCompleted: vi.fn(),
  markCompletionSynced: vi.fn(),
  markPromptGenerationFailed: vi.fn(),
  isComposerDisabled: false,
}));

const authorizationValue = vi.hoisted(() => ({
  hasPermission: () => true,
  canAccessRoute: () => true,
  user: { email: "test@example.com" },
}));

vi.mock("@assistant-ui/react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@assistant-ui/react")>();
  return {
    ...actual,
    AssistantRuntimeProvider: ({ children }: { children: React.ReactNode }) => (
      <>{children}</>
    ),
    useAuiState: <T,>(selector: (state: unknown) => T) => {
      auiStateCalls += 1;
      if (auiStateCalls - auiStateLogged >= 5000) {
        auiStateLogged = auiStateCalls;
        console.warn(`[harness] useAuiState calls: ${auiStateCalls}`);
      }
      if (auiStateCalls > 60000) {
        throw new Error(`useAuiState invoked ${auiStateCalls} times`);
      }
      return selector(runtimeState);
    },
    useRemoteThreadListRuntime: () => runtimeMock,
  };
});

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({
    replace: vi.fn(),
    push: vi.fn(),
  })),
  useParams: vi.fn(() => ({ locale: "zh" })),
}));

vi.mock("react-i18next", () => {
  const translation = {
    t: (key: string, fallback?: string) => fallback ?? key,
    i18n: { language: "zh" },
  };
  return {
    useTranslation: () => translation,
    initReactI18next: { type: "3rdParty", init: () => {} },
    I18nextProvider: ({ children }: { children?: React.ReactNode }) => (
      <>{children}</>
    ),
  };
});

vi.mock("@/app/newchat/assistant-ui/chat", () => ({
  Chat: () => <div>workbench chat</div>,
}));

vi.mock("@/app/newchat/assistant-ui/threadlist-sidebar", () => ({
  ThreadListSidebar: ({
    onNewConversation,
  }: {
    onNewConversation: () => void;
  }) => (
    <div>
      workbench sidebar
      <button onClick={() => onNewConversation()}>new conversation</button>
    </div>
  ),
}));

vi.mock("@/app/newchat/adapter/server-dictation-adapter", () => ({
  ServerDictationAdapter: class {
    constructor() {}
  },
}));

vi.mock("@/hooks/agent/usePublishedAgentList", () => ({
  usePublishedAgentList: () =>
    publishedAgentListValue.usePublishedAgentListValue,
}));

vi.mock("@/hooks/useConfig", () => ({
  useConfig: () => ({ modelConfig: undefined }),
}));

vi.mock("@/hooks/model/useModelList", () => ({
  useModelList: () => ({ llmModels: [], availableLlmModels: [], isLoading: false }),
}));

vi.mock("@/services/conversationService", () => ({
  conversationService: {
    getKnowledgeCapabilities: vi.fn().mockResolvedValue(null),
    getById: vi.fn().mockResolvedValue({}),
    rename: vi.fn().mockResolvedValue(true),
  },
}));

vi.mock("@/services/agentConfigService", () => ({
  createSkill: vi.fn().mockResolvedValue({ success: true }),
  searchAgentInfo: vi.fn().mockResolvedValue({ success: true, data: null }),
}));

vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => authorizationValue,
}));

vi.mock("@/components/ui/sidebar", () => ({
  SidebarProvider: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}));

vi.mock("@/contexts/nl2AgentFlow", () => ({
  Nl2AgentFlowProvider: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
  useNl2AgentFlow: () => nl2AgentFlowValue,
}));

vi.mock("@/stores/agentStore", () => ({
  useAgentStore: Object.assign(vi.fn(), {
    getState: () => ({ replaceServerSnapshot: vi.fn(() => true) }),
  }),
}));

vi.mock("@/features/workbench/hooks/useConversationResume", () => ({
  useConversationResume: vi.fn(),
}));

vi.mock("@/features/workbench/hooks/useConversationRouteGuard", () => ({
  useConversationRouteGuard: vi.fn(),
}));

vi.mock("@/features/workbench/api", () => ({
  fetchWorkbenchBootstrap: vi.fn().mockResolvedValue(null),
}));

vi.mock("@/features/workbench", () => ({
  getWorkbenchSendability: () => ({}),
  deriveConversationMode: () => "generic_chat",
  previewWorkbenchAgent: () => null,
  SkillPicker: () => null,
}));

vi.mock("@/features/workbench/components/AgentPicker", () => ({
  AgentPicker: () => null,
}));

vi.mock("@/features/workbench/components/CreationActions", () => ({
  CreationActions: () => null,
}));

vi.mock("@/features/workbench/components/CreationResultCards", () => ({
  SkillCreationResultCard: () => null,
}));

vi.mock("@/features/workbench/components/SkillPopoverContent", () => ({
  SkillPopoverContent: () => null,
}));

vi.mock("@/features/workbench/components/KnowledgePopoverContent", () => ({
  KnowledgePopoverContent: () => null,
}));

describe("workbench new conversation", () => {
  beforeEach(() => {
    // The workbench vitest config restores mocks before each test, so every
    // implementation has to be re-established here.
    switchToNewThread.mockReset().mockResolvedValue(undefined);
    reloadThreads.mockReset().mockResolvedValue(undefined);
    initializeThread.mockReset().mockResolvedValue(undefined);
    updateThreadCustom.mockReset().mockResolvedValue(undefined);
    setRunConfig.mockReset();
    runtimeMock.threads.getItemById.mockReset().mockReturnValue({
      initialize: initializeThread,
      updateCustom: updateThreadCustom,
    });
    runtimeMock.threads.getState.mockReset().mockReturnValue({
      mainThreadId: "thread-1",
    });
    runtimeMock.thread.getState
      .mockReset()
      .mockReturnValue({ isRunning: false });
    runtimeState = {
      threads: {
        mainThreadId: "thread-1",
        isLoading: false,
        threadItems: [{ id: "thread-1", remoteId: "88" }],
      },
      thread: { isLoading: false, isRunning: false },
    };
    window.history.replaceState({}, "", "/zh/workbench");
  });

  it("reloads the conversation list after starting a new conversation", async () => {
    const user = userEvent.setup();
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <WorkbenchPage />
      </QueryClientProvider>
    );

    expect(await screen.findByText("workbench sidebar")).toBeInTheDocument();

    await user.click(screen.getByText("new conversation"));

    await waitFor(() => {
      expect(switchToNewThread).toHaveBeenCalledTimes(1);
    });
    // Without the reload, the conversation the user just left — created on
    // the server when its first message was sent — vanished from the sidebar
    // until a manual page refresh.
    expect(reloadThreads).toHaveBeenCalledTimes(1);
    expect(switchToNewThread.mock.invocationCallOrder[0]).toBeLessThan(
      reloadThreads.mock.invocationCallOrder[0]
    );
  });
});

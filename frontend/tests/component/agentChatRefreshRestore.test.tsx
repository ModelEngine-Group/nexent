// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import React from "react";
import { screen } from "@testing-library/dom";
import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Home from "../../app/[locale]/newchat/page";

const switchToNewThread = vi.fn().mockResolvedValue(undefined);
const reloadThreads = vi.fn().mockResolvedValue(undefined);
const initializeThread = vi.fn().mockResolvedValue(undefined);
const updateThreadCustom = vi.fn().mockResolvedValue(undefined);

const runtimeMock = {
  threads: {
    switchToNewThread,
    reload: reloadThreads,
    getItemById: vi.fn(() => ({
      initialize: initializeThread,
      updateCustom: updateThreadCustom,
    })),
    getState: vi.fn(() => ({ mainThreadId: "main-thread" })),
  },
  thread: { composer: { setRunConfig: vi.fn() } },
};

let runtimeState = {
  threads: {
    mainThreadId: "main-thread",
    isLoading: false,
    threadItems: [] as Array<{ id: string; remoteId?: string }>,
  },
  thread: { isLoading: false, isRunning: false },
};

const agent = {
  id: "41",
  agent_id: 41,
  name: "medic_2",
  display_name: "Fixed Agent",
  current_version_no: 1,
};
type PageAgent = typeof agent;

let capturedRuntimeOptions: Record<string, unknown> | undefined;

vi.mock("@assistant-ui/react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@assistant-ui/react")>();
  return {
    ...actual,
    AssistantRuntimeProvider: ({ children }: { children: React.ReactNode }) => (
      <>{children}</>
    ),
    useAuiState: <T,>(selector: (state: unknown) => T) =>
      selector(runtimeState),
    useRemoteThreadListRuntime: (options: Record<string, unknown>) => {
      capturedRuntimeOptions = options;
      return runtimeMock;
    },
  };
});

const usePublishedAgentList = vi.fn(() => ({
  isLoading: false,
  agents: [agent],
}));

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({
    replace: vi.fn(),
    push: vi.fn(),
  })),
  useParams: vi.fn(() => ({ locale: "zh" })),
}));

vi.mock("../../app/[locale]/newchat/assistant-ui/chat", () => ({
  Chat: ({
    selectedAgent,
    onAgentSelected,
    onBack,
  }: {
    selectedAgent: PageAgent | null;
    onAgentSelected: (agent: PageAgent) => void;
    onBack: () => void;
  }) => (
    <>
      {selectedAgent ? (
        <div>
          <div>Agent chat: {selectedAgent.display_name}</div>
          <button onClick={onBack}>back to list</button>
        </div>
      ) : (
        <div>
          <div>Agent list</div>
          <button onClick={() => onAgentSelected(agent)}>select agent</button>
        </div>
      )}
    </>
  ),
}));

vi.mock("../../app/[locale]/newchat/assistant-ui/threadlist-sidebar", () => ({
  ThreadListSidebar: () => <div>thread list</div>,
}));

vi.mock("@/hooks/agent/usePublishedAgentList", () => ({
  usePublishedAgentList: () => usePublishedAgentList(),
}));
vi.mock("@/hooks/chat/useConversationAgentHistory", () => ({
  useConversationAgentHistory: () => ({ data: undefined }),
}));
vi.mock("@/hooks/chat/useComposerResources", () => ({
  useComposerKnowledgeBases: () => ({ dataUpdatedAt: 0 }),
}));
vi.mock("@/hooks/useConfig", () => ({
  useConfig: () => ({ modelConfig: undefined }),
}));

vi.mock("@/services/conversationService", () => ({
  conversationService: {
    getKnowledgeCapabilities: vi.fn().mockResolvedValue(null),
    getById: vi.fn().mockResolvedValue({}),
  },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const CONVERSATION_KEY = "nexent_last_chat_conversation_id";
const AGENT_KEY = "nexent_last_chat_agent_id";

describe("newchat refresh restore wiring", () => {
  beforeEach(() => {
    switchToNewThread.mockClear().mockResolvedValue(undefined);
    reloadThreads.mockClear().mockResolvedValue(undefined);
    initializeThread.mockClear();
    updateThreadCustom.mockClear();
    capturedRuntimeOptions = undefined;
    window.sessionStorage.clear();
    runtimeState = {
      threads: {
        mainThreadId: "main-thread",
        isLoading: false,
        threadItems: [],
      },
      thread: { isLoading: false, isRunning: false },
    };
    window.history.replaceState({}, "", "/zh/newchat");
  });

  it("passes the last viewed conversation as the runtime's initial thread", () => {
    window.sessionStorage.setItem(CONVERSATION_KEY, "77");
    render(<Home />);

    expect(capturedRuntimeOptions?.threadId).toBeUndefined();
    expect(capturedRuntimeOptions?.initialThreadId).toBe("77");
  });

  it("starts on the landing when the user returns via navigation, not refresh", () => {
    // First visit: the stored conversation is restored, like a refresh.
    window.sessionStorage.setItem(CONVERSATION_KEY, "77");
    const { unmount } = render(<Home />);
    expect(capturedRuntimeOptions?.initialThreadId).toBe("77");

    // Leaving the chat route (e.g. to the agent workbench) runs the unmount
    // cleanup, unlike a browser refresh: the marker must not survive.
    unmount();
    expect(window.sessionStorage.getItem(CONVERSATION_KEY)).toBeNull();

    // Returning through the menu therefore starts on the landing page.
    // (The mocked runtime hook overwrites the captured options on every
    // render, so they can be asserted directly after the second render.)
    render(<Home />);
    expect(capturedRuntimeOptions?.initialThreadId).toBeUndefined();
    expect(screen.getByText("Agent list")).toBeInTheDocument();
  });

  it("reopens a blank conversation of the stored agent when no conversation was saved", async () => {
    window.sessionStorage.setItem(AGENT_KEY, "41");
    render(<Home />);

    expect(capturedRuntimeOptions?.initialThreadId).toBeUndefined();
    expect(
      await screen.findByText("Agent chat: Fixed Agent")
    ).toBeInTheDocument();
  });

  it("lets deep-link parameters own the initial screen instead of the stored view", async () => {
    window.sessionStorage.setItem(CONVERSATION_KEY, "77");
    window.sessionStorage.setItem(AGENT_KEY, "41");
    window.history.replaceState({}, "", "/zh/newchat?agent_id=41");
    render(<Home />);

    expect(capturedRuntimeOptions?.initialThreadId).toBeUndefined();
    // The deep link still selects the agent.
    expect(
      await screen.findByText("Agent chat: Fixed Agent")
    ).toBeInTheDocument();
  });

  it("starts on the landing page when nothing was stored", () => {
    render(<Home />);

    expect(capturedRuntimeOptions?.initialThreadId).toBeUndefined();
    expect(screen.getByText("Agent list")).toBeInTheDocument();
  });

  it("keeps the saved conversation while the initial view is still loading", () => {
    window.sessionStorage.setItem(CONVERSATION_KEY, "77");
    // Agents are still loading: no view has been established yet, so the
    // marker must survive this window for a second refresh to restore.
    usePublishedAgentList.mockReturnValue({ isLoading: true, agents: [] });
    try {
      render(<Home />);

      expect(window.sessionStorage.getItem(CONVERSATION_KEY)).toBe("77");
    } finally {
      usePublishedAgentList.mockImplementation(() => ({
        isLoading: false,
        agents: [agent],
      }));
    }
  });

  it("records the viewed conversation and clears it when returning to the landing", async () => {
    const user = userEvent.setup();
    runtimeState = {
      threads: {
        mainThreadId: "main-thread",
        isLoading: false,
        threadItems: [{ id: "main-thread", remoteId: "88" }],
      },
      thread: { isLoading: false, isRunning: false },
    };
    render(<Home />);

    await user.click(screen.getByText("select agent"));
    await screen.findByText("Agent chat: Fixed Agent");
    expect(window.sessionStorage.getItem(CONVERSATION_KEY)).toBe("88");
    expect(window.sessionStorage.getItem(AGENT_KEY)).toBeNull();

    await user.click(screen.getByText("back to list"));
    await screen.findByText("Agent list");
    expect(window.sessionStorage.getItem(CONVERSATION_KEY)).toBeNull();
    expect(window.sessionStorage.getItem(AGENT_KEY)).toBeNull();
  });

  it("stores the agent id while the user is in an unsent blank conversation", async () => {
    const user = userEvent.setup();
    render(<Home />);

    await user.click(screen.getByText("select agent"));
    await screen.findByText("Agent chat: Fixed Agent");
    // The mocked runtime keeps the local thread id, so no conversation is
    // stored — only the agent selection survives the refresh.
    expect(window.sessionStorage.getItem(CONVERSATION_KEY)).toBeNull();
    expect(window.sessionStorage.getItem(AGENT_KEY)).toBe("41");
  });
});

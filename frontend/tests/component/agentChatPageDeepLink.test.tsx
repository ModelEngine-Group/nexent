import React from "react";
import { screen } from "@testing-library/dom";
import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import Home from "../../app/[locale]/newchat/page";

const switchToNewThread = vi.fn();

const runtimeMock = {
  threads: {
    switchToNewThread,
    getItemById: vi.fn(() => ({
      initialize: vi.fn().mockResolvedValue(undefined),
      updateCustom: vi.fn().mockResolvedValue(undefined),
    })),
    getState: vi.fn(() => ({ mainThreadId: "main-thread" })),
  },
  thread: { composer: { setRunConfig: vi.fn() } },
};

const runtimeState = {
  threads: {
    mainThreadId: "main-thread",
    isLoading: false,
    threadItems: [],
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

vi.mock("@assistant-ui/react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@assistant-ui/react")>();
  return {
    ...actual,
    AssistantRuntimeProvider: ({ children }: { children: React.ReactNode }) => (
      <>{children}</>
    ),
    useAuiState: <T,>(selector: (state: unknown) => T) =>
      selector(runtimeState),
    useRemoteThreadListRuntime: () => runtimeMock,
  };
});

const usePublishedAgentList = vi.fn(() => ({
  isLoading: false,
  agents: [agent],
}));

vi.mock("../../app/[locale]/newchat/assistant-ui/chat", () => ({
  Chat: ({
    selectedAgent,
    isLoadingAgents,
    onAgentSelected,
    onBack,
  }: {
    selectedAgent: PageAgent | null;
    isLoadingAgents: boolean;
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
vi.mock("../../app/[locale]/newchat/assistant-ui/agent-landing", () => ({
  AgentLandingPage: ({
    onSelectAgent,
  }: {
    onSelectAgent: (agent: PageAgent) => void;
  }) => (
    <div>
      <div>Agent list</div>
      <button onClick={() => onSelectAgent(agent)}>select agent</button>
    </div>
  ),
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

describe("newchat Agent deep-link page wiring", () => {
  beforeEach(() => {
    switchToNewThread.mockReset();
    window.history.replaceState({}, "", "/zh/newchat?agent_id=41");
  });

  it("selects the target Agent even while the runtime thread switch is pending", async () => {
    switchToNewThread.mockImplementation(
      () => new Promise<void>(() => undefined)
    );
    render(<Home />);

    expect(
      await screen.findByText("Agent chat: Fixed Agent")
    ).toBeInTheDocument();
    expect(switchToNewThread).toHaveBeenCalledTimes(1);
  });

  it("consumes the deep link once and keeps manual selection working", async () => {
    switchToNewThread.mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<Home />);

    expect(
      await screen.findByText("Agent chat: Fixed Agent")
    ).toBeInTheDocument();
    const callsAfterDeepLink = switchToNewThread.mock.calls.length;
    await user.click(screen.getByRole("button", { name: "back to list" }));
    expect(await screen.findByText("Agent list")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "select agent" }));
    expect(
      await screen.findByText("Agent chat: Fixed Agent")
    ).toBeInTheDocument();
    expect(switchToNewThread.mock.calls.length).toBe(callsAfterDeepLink + 3);
  });
});

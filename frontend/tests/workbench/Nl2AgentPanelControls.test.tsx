// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { createRef, type ReactNode } from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type {
  ChatModelAdapter,
  ChatModelRunOptions,
} from "@assistant-ui/react";
import { message } from "antd";
import { Nl2AgentFlowProvider, useNl2AgentFlow } from "@/contexts/nl2AgentFlow";
import zh from "@/public/locales/zh/common.json";
import en from "@/public/locales/en/common.json";
import type { ThreadProps } from "@/app/newchat/assistant-ui/thread";
import {
  Nl2AgentChatPanel,
  type Nl2AgentChatPanelHandle,
} from "@/app/newchat/assistant-ui/nl2agent-chat-panel";

const fixture = vi.hoisted(() => {
  const state = { isRunning: false };
  return {
    state,
    locale: null as "zh" | "en" | null,
    controls: {
      selectedModelId: "3",
      onModelChange: vi.fn(),
      deepThinking: true,
      onDeepThinkingChange: vi.fn(),
      thinkingEffort: "xhigh",
      onThinkingEffortChange: vi.fn(),
      reasoningBudgetTokens: 2048,
      onReasoningBudgetTokensChange: vi.fn(),
      modelParameterSettings: {
        value: { temperature: 0.7, top_p: 0.9 },
      },
      snapshot: {
        model_id: 3,
        generation_config: {
          deep_thinking: true,
          thinking_effort: "xhigh",
          temperature: 0.7,
          top_p: 0.9,
        },
      },
      canCreate: true,
      canSend: true,
    },
    runtime: {
      thread: {
        subscribe: () => () => {},
        getState: () => state,
        cancelRun: vi.fn(),
        append: vi.fn(),
        import: vi.fn(),
        reset: vi.fn(),
        composer: { setText: vi.fn(), reset: vi.fn(async () => {}) },
      },
    },
    history: {
      items: [] as Array<{
        conversation_id: number;
        conversation_title: string;
        create_time: number;
        update_time: number;
      }>,
      total: 3,
      pending: false,
      failed: false,
      fetchingMore: false,
      hasMore: false,
      loadMore: vi.fn(),
      refetch: vi.fn(),
      refresh: vi.fn(),
    },
    getById: vi.fn(),
    historyLoad: vi.fn(),
    thread: vi.fn(),
    remoteRun: vi.fn(async function* (_options: ChatModelRunOptions) {
      yield { content: [] };
    }),
    adapter: undefined as ChatModelAdapter | undefined,
  };
});

vi.mock("@/hooks/chat/useCreatorHistories", () => ({
  useCreatorHistories: () => fixture.history,
}));
vi.mock("@/services/conversationService", () => ({
  conversationService: { getById: fixture.getById },
}));
vi.mock("@/app/newchat/adapter/conversation-thread-list-adapter", () => ({
  RemoteConversationHistoryAdapter: class {
    load() {
      return fixture.historyLoad();
    }
  },
}));
vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({
    t: (key: string) =>
      fixture.locale
        ? ((
            (fixture.locale === "zh" ? zh : en) as unknown as Record<
              string,
              string
            >
          )[key] ?? key)
        : key,
  }),
}));
vi.mock("@assistant-ui/react", () => ({
  AssistantRuntimeProvider: ({ children }: { children: ReactNode }) => children,
  useLocalRuntime: (adapter: ChatModelAdapter) => {
    fixture.adapter = adapter;
    return fixture.runtime;
  },
}));
vi.mock("@/components/ui/tooltip", () => ({
  TooltipProvider: ({ children }: { children: ReactNode }) => children,
}));
vi.mock("@/hooks/useConfig", () => ({
  useConfig: () => ({ modelConfig: { stt: {} } }),
}));
vi.mock("@/features/model-controls/useCreatorModelControls", () => ({
  useCreatorModelControls: () => fixture.controls,
}));
vi.mock("@/app/newchat/adapter/attachment-adapter", () => ({
  compositeAttachmentAdapter: {},
}));
vi.mock("@/app/newchat/adapter/server-dictation-adapter", () => ({
  ServerDictationAdapter: class {},
}));
vi.mock("@/app/newchat/adapter/remote-chat-model-adapter", () => ({
  remoteChatModelAdapter: { run: fixture.remoteRun },
}));
vi.mock("@/app/newchat/assistant-ui/thread", () => ({
  Thread: (props: ThreadProps) => {
    fixture.thread(props);
    return (
      <section data-testid="creator-welcome">{props.welcomeContent}</section>
    );
  },
}));

afterEach(() => message.destroy());

beforeEach(() => {
  vi.clearAllMocks();
  fixture.state.isRunning = false;
  fixture.locale = null;
  fixture.history.items = [];
  fixture.history.total = 3;
  fixture.history.failed = false;
  fixture.history.hasMore = false;
  fixture.getById.mockReset();
  fixture.historyLoad.mockResolvedValue({ messages: [] });
  fixture.controls.canCreate = true;
  fixture.controls.canSend = true;
});

it("keeps tenant model controls connected while shared suggestions only fill input", () => {
  render(<Nl2AgentChatPanel agentId={42} agentDescription="Existing agent" />);
  const props = fixture.thread.mock.calls.at(-1)![0] as ThreadProps;
  expect(props).toMatchObject({
    modelSelectionScope: "tenant",
    showModelSelector: true,
    readOnly: false,
    selectedModelId: "3",
    onModelChange: fixture.controls.onModelChange,
    deepThinking: true,
    thinkingEffort: "xhigh",
    reasoningBudgetTokens: 2048,
    onDeepThinkingChange: fixture.controls.onDeepThinkingChange,
    onThinkingEffortChange: fixture.controls.onThinkingEffortChange,
    onReasoningBudgetTokensChange:
      fixture.controls.onReasoningBudgetTokensChange,
    modelParameterSettings: fixture.controls.modelParameterSettings,
  });
  expect(props.composerTools).toBeUndefined();
  expect(props.onChatModeChange).toBeUndefined();
  expect(props.workbenchResources).toBeUndefined();
  expect(screen.getByText("nl2agent.configuration.title")).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", {
      name: /nl2agent.suggestions.generatePrompts.title/,
    })
  );
  expect(fixture.runtime.thread.composer.setText).toHaveBeenCalledWith(
    "nl2agent.suggestions.generatePrompts.prompt"
  );
  expect(fixture.runtime.thread.append).not.toHaveBeenCalled();
  expect(fixture.remoteRun).not.toHaveBeenCalled();
});

it.each(
  ["", "Existing agent"].flatMap((agentDescription) =>
    ["permission", "disabled", "running"].map((condition) => ({
      agentDescription,
      condition,
    }))
  )
)(
  "blocks welcome actions when $condition with description '$agentDescription'",
  ({ agentDescription, condition }) => {
    fixture.controls.canCreate = condition !== "permission";
    fixture.state.isRunning = condition === "running";
    render(
      <Nl2AgentChatPanel
        disabled={condition === "disabled"}
        agentDescription={agentDescription}
      />
    );
    for (const button of within(
      screen.getByTestId("creator-welcome")
    ).getAllByRole("button"))
      expect(button).toBeDisabled();
    const props = fixture.thread.mock.calls.at(-1)![0] as ThreadProps;
    if (condition !== "running") expect(props.readOnly).toBe(true);
  }
);

it("retains per-turn model snapshots in the creation adapter including canonical sampling", async () => {
  render(<Nl2AgentChatPanel agentId={42} />);
  const result = fixture.adapter!.run({
    messages: [],
    runConfig: { custom: { retained: true } },
  } as never);
  for await (const chunk of result as AsyncIterable<unknown>) {
    void chunk;
  }
  expect(fixture.remoteRun).toHaveBeenCalledWith(
    expect.objectContaining({
      runConfig: {
        custom: expect.objectContaining({
          retained: true,
          runtimeMode: "nl2agent",
          agentId: 42,
          turnModelControls: fixture.controls.snapshot,
        }),
      },
    })
  );
  expect(JSON.stringify(fixture.remoteRun.mock.calls)).toContain("temperature");
});

it("blocks invalid-model sends and imperative prompts without a creation target", async () => {
  const ref = createRef<Nl2AgentChatPanelHandle>();
  fixture.controls.canSend = false;
  const view = render(
    <Nl2AgentChatPanel
      ref={ref}
      agentId={42}
      showOptimizationSuggestions={false}
    />
  );
  ref.current!.sendPrompt("create");
  const result = fixture.adapter!.run({ messages: [] } as never);
  for await (const chunk of result as AsyncIterable<unknown>) {
    void chunk;
  }
  expect(fixture.remoteRun).not.toHaveBeenCalled();
  expect(fixture.runtime.thread.append).not.toHaveBeenCalled();
  expect(
    within(screen.getByTestId("creator-welcome")).queryByRole("button")
  ).not.toBeInTheDocument();
  fixture.controls.canSend = true;
  view.rerender(<Nl2AgentChatPanel ref={ref} agentId={null} />);
  ref.current!.sendPrompt("create");
  expect(fixture.runtime.thread.append).not.toHaveBeenCalled();
});

it.each([undefined, null, "", " \n\t "])(
  "shows workbench creation examples for description %s",
  (agentDescription) => {
    render(
      <Nl2AgentChatPanel agentId={42} agentDescription={agentDescription} />
    );
    expect(
      within(screen.getByTestId("creator-welcome")).getAllByRole("button")
    ).toHaveLength(3);
    expect(
      screen.getByText(
        "workbench.creationExamples.agent.documentOrganizer.title"
      )
    ).toBeInTheDocument();
    expect(
      screen.queryByText("nl2agent.suggestions.generatePrompts.title")
    ).not.toBeInTheDocument();
  }
);

it.each(["zh", "en"] as const)(
  "uses current workbench creation copy and complete prompts in %s without sending",
  (locale) => {
    fixture.locale = locale;
    const copy = (locale === "zh" ? zh : en) as unknown as Record<
      string,
      string
    >;
    render(<Nl2AgentChatPanel agentId={42} />);
    const keys = ["documentOrganizer", "medicalBriefing", "eventPromotion"];
    for (const key of keys) {
      const prefix = `workbench.creationExamples.agent.${key}`;
      const button = screen.getByRole("button", {
        name: `${copy[`${prefix}.title`]} ${copy[`${prefix}.description`]}`,
      });
      expect(button).not.toHaveTextContent(copy[prefix]);
      fireEvent.click(button);
      expect(fixture.runtime.thread.composer.setText).toHaveBeenLastCalledWith(
        copy[prefix]
      );
    }
    const props = fixture.thread.mock.calls.at(-1)![0] as ThreadProps;
    expect(props.agent?.example_questions).toEqual(
      keys.map((key) => copy[`workbench.creationExamples.agent.${key}`])
    );
    expect(fixture.runtime.thread.append).not.toHaveBeenCalled();
    expect(fixture.remoteRun).not.toHaveBeenCalled();
  }
);

it("switches examples on description changes while retaining the visibility opt-out", () => {
  const view = render(<Nl2AgentChatPanel agentId={42} agentDescription="" />);
  view.rerender(
    <Nl2AgentChatPanel agentId={42} agentDescription=" Existing agent " />
  );
  expect(
    within(screen.getByTestId("creator-welcome")).getAllByRole("button")
  ).toHaveLength(4);
  expect(
    screen.getByText("nl2agent.suggestions.generatePrompts.title")
  ).toBeInTheDocument();
  view.rerender(<Nl2AgentChatPanel agentId={42} agentDescription="" />);
  expect(
    within(screen.getByTestId("creator-welcome")).getAllByRole("button")
  ).toHaveLength(3);
  for (const agentDescription of ["", "Existing agent"]) {
    view.rerender(
      <Nl2AgentChatPanel
        agentId={42}
        agentDescription={agentDescription}
        showOptimizationSuggestions={false}
      />
    );
    expect(
      within(screen.getByTestId("creator-welcome")).queryByRole("button")
    ).not.toBeInTheDocument();
  }
  expect(fixture.runtime.thread.append).not.toHaveBeenCalled();
  expect(fixture.runtime.thread.cancelRun).not.toHaveBeenCalled();
});

it("shows scoped history count, restores a turn and starts another conversation for the same target", async () => {
  fixture.locale = "zh";
  fixture.history.items = [
    {
      conversation_id: 12,
      conversation_title: "Build weather agent",
      create_time: 1,
      update_time: 2,
    },
  ];
  fixture.getById.mockResolvedValue({
    agent_system_key: "nl2agent_main",
    target: { type: "agent", id: 42 },
    message: [],
  });
  const saved = { messages: [{ message: { id: "old-turn" } }] };
  fixture.historyLoad.mockResolvedValue(saved);
  const conversationChanged = vi.fn();
  render(
    <Nl2AgentChatPanel
      agentId={42}
      onConversationChange={conversationChanged}
    />
  );
  fireEvent.click(screen.getByRole("button", { name: "历史 3" }));
  fireEvent.click(
    await screen.findByRole("button", { name: /Build weather agent/ })
  );
  await waitFor(() =>
    expect(fixture.runtime.thread.import).toHaveBeenCalledWith(saved)
  );
  expect(conversationChanged).toHaveBeenCalledExactlyOnceWith(42);
  async function send() {
    const result = fixture.adapter!.run({
      messages: [],
      runConfig: {},
      context: {},
      abortSignal: new AbortController().signal,
    } as never);
    if (Symbol.asyncIterator in result)
      for await (const chunk of result) void chunk;
    else await result;
  }
  await act(send);
  expect(
    fixture.remoteRun.mock.calls.at(-1)?.[0].runConfig?.custom
  ).toMatchObject({ agentId: 42, threadId: "12" });
  fireEvent.click(screen.getByRole("button", { name: "新会话" }));
  await waitFor(() =>
    expect(fixture.runtime.thread.reset).toHaveBeenCalledOnce()
  );
  expect(conversationChanged).toHaveBeenCalledTimes(2);
  await act(send);
  expect(
    fixture.remoteRun.mock.calls.at(-1)?.[0].runConfig?.custom?.agentId
  ).toBe(42);
  expect(
    fixture.remoteRun.mock.calls.at(-1)?.[0].runConfig?.custom?.threadId
  ).toBeUndefined();
});

it("blocks history switching during generation", () => {
  fixture.locale = "zh";
  fixture.state.isRunning = true;
  render(<Nl2AgentChatPanel agentId={42} />);
  expect(screen.getByRole("button", { name: "历史 3" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "新会话" })).toBeDisabled();
});

it("hides the configuration navigation result card in the NL2Agent editor", () => {
  render(<Nl2AgentChatPanel agentId={42} />);
  expect(fixture.thread.mock.calls.at(-1)?.[0]).toMatchObject({
    showAgentCreationResult: false,
  });
});

it("rejects a history for another target without clearing the current thread", async () => {
  fixture.locale = "zh";
  fixture.history.items = [
    {
      conversation_id: 12,
      conversation_title: "Other target",
      create_time: 1,
      update_time: 2,
    },
  ];
  fixture.getById.mockResolvedValue({
    agent_system_key: "nl2agent_main",
    target: { type: "agent", id: 99 },
  });
  render(<Nl2AgentChatPanel agentId={42} />);
  fireEvent.click(screen.getByRole("button", { name: "历史 3" }));
  fireEvent.click(await screen.findByRole("button", { name: /Other target/ }));
  await waitFor(() => expect(fixture.getById).toHaveBeenCalledWith("12"));
  expect(fixture.runtime.thread.import).not.toHaveBeenCalled();
  expect(fixture.runtime.thread.reset).not.toHaveBeenCalled();
});

it("shows empty history and offers a new conversation without pre-creating a record", async () => {
  fixture.locale = "zh";
  fixture.history.total = 0;
  render(<Nl2AgentChatPanel agentId={42} />);
  fireEvent.click(screen.getByRole("button", { name: "历史 0" }));
  expect(await screen.findByText("暂无历史对话")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "新会话" }));
  await waitFor(() =>
    expect(fixture.runtime.thread.reset).toHaveBeenCalledOnce()
  );
  expect(fixture.remoteRun).not.toHaveBeenCalled();
});

it("exposes a retry when the history list fails", async () => {
  fixture.locale = "zh";
  fixture.history.failed = true;
  render(<Nl2AgentChatPanel agentId={42} />);
  fireEvent.click(screen.getByRole("button", { name: "历史 —" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "历史记录加载失败"
  );
  fireEvent.click(screen.getByRole("button", { name: "重试" }));
  expect(fixture.history.refetch).toHaveBeenCalled();
});

it("ignores a history load completed after the panel is removed", async () => {
  fixture.locale = "zh";
  fixture.history.items = [
    {
      conversation_id: 12,
      conversation_title: "Slow history",
      create_time: 1,
      update_time: 2,
    },
  ];
  let resolve!: (value: unknown) => void;
  fixture.getById.mockImplementation(
    () =>
      new Promise((done) => {
        resolve = done;
      })
  );
  const panel = render(<Nl2AgentChatPanel agentId={42} />);
  fireEvent.click(screen.getByRole("button", { name: "历史 3" }));
  fireEvent.click(await screen.findByRole("button", { name: /Slow history/ }));
  panel.unmount();
  await act(async () => {
    resolve({
      agent_system_key: "nl2agent_main",
      target: { type: "agent", id: 42 },
    });
  });
  expect(fixture.historyLoad).not.toHaveBeenCalled();
  expect(fixture.runtime.thread.import).not.toHaveBeenCalled();
  expect(fixture.runtime.thread.reset).not.toHaveBeenCalled();
});

function EditorWithFlow() {
  const {
    resetFlow,
    registerCard,
    markRunStarted,
    markGenerationStopped,
    isFormLocked,
  } = useNl2AgentFlow();
  return (
    <>
      <button
        onClick={() => {
          resetFlow(42);
          markRunStarted(42);
          registerCard("previous-session", "installed_resource_binding");
        }}
      >
        Previous session pending
      </button>
      <input aria-label="Agent configuration" disabled={isFormLocked} />
      <Nl2AgentChatPanel
        agentId={42}
        onConversationChange={markGenerationStopped}
      />
    </>
  );
}

it("clears a previous conversation's form lock on restore and new conversation", async () => {
  fixture.locale = "zh";
  fixture.history.items = [
    {
      conversation_id: 12,
      conversation_title: "Completed generation",
      create_time: 1,
      update_time: 2,
    },
  ];
  fixture.getById.mockResolvedValue({
    agent_system_key: "nl2agent_main",
    target: { type: "agent", id: 42 },
  });
  render(
    <Nl2AgentFlowProvider>
      <EditorWithFlow />
    </Nl2AgentFlowProvider>
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Previous session pending" })
  );
  expect(
    screen.getByRole("textbox", { name: "Agent configuration" })
  ).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "历史 3" }));
  fireEvent.click(
    await screen.findByRole("button", { name: /Completed generation/ })
  );
  await waitFor(() =>
    expect(fixture.runtime.thread.import).toHaveBeenCalledOnce()
  );
  expect(
    screen.getByRole("textbox", { name: "Agent configuration" })
  ).toBeEnabled();
  fireEvent.click(
    screen.getByRole("button", { name: "Previous session pending" })
  );
  expect(
    screen.getByRole("textbox", { name: "Agent configuration" })
  ).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "新会话" }));
  await waitFor(() =>
    expect(fixture.runtime.thread.reset).toHaveBeenCalledOnce()
  );
  expect(
    screen.getByRole("textbox", { name: "Agent configuration" })
  ).toBeEnabled();
});

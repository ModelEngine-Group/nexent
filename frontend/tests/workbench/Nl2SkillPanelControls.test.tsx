// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ReactNode } from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { message } from "antd";
import type {
  ChatModelAdapter,
  ChatModelRunOptions,
} from "@assistant-ui/react";
import zh from "@/public/locales/zh/common.json";
import { Nl2SkillChatPanel } from "@/app/newchat/assistant-ui/nl2skill-chat-panel";

const state = vi.hoisted(() => {
  const threadState = { isRunning: false };
  return {
    threadState,
    adapter: undefined as ChatModelAdapter | undefined,
    controls: { canSend: true, canCreate: true, snapshot: { model_id: 3 } },
    history: {
      items: [] as Array<{
        conversation_id: number;
        conversation_title: string;
        create_time: number;
      }>,
      total: 2,
      pending: false,
      failed: false,
      fetchingMore: false,
      hasMore: false,
      loadMore: vi.fn(),
      refetch: vi.fn(),
      refresh: vi.fn(),
    },
    query: vi.fn(),
    getById: vi.fn(),
    load: vi.fn(),
    onId: vi.fn(),
    events: vi.fn(),
    chat: vi.fn(),
    draft: vi.fn(() => ({
      skill_name: "sample",
      files: [{ path: "SKILL.md", content: "draft" }],
    })),
    run: vi.fn(async function* (_options: ChatModelRunOptions) {
      void _options;
      yield { content: [] };
    }),
    runtime: {
      thread: {
        subscribe: () => () => {},
        getState: () => threadState,
        import: vi.fn(),
        reset: vi.fn(),
        composer: { reset: vi.fn(async () => {}) },
      },
    },
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => (zh as unknown as Record<string, string>)[key] ?? key,
  }),
}));
vi.mock("@/components/ui/tooltip", () => ({
  TooltipProvider: ({ children }: { children: ReactNode }) => children,
}));
vi.mock("@assistant-ui/react", () => ({
  AssistantRuntimeProvider: ({ children }: { children: ReactNode }) => children,
  useLocalRuntime: (adapter: ChatModelAdapter) => {
    state.adapter = adapter;
    return state.runtime;
  },
}));
vi.mock("@/features/model-controls/useCreatorModelControls", () => ({
  useCreatorModelControls: () => state.controls,
}));
vi.mock("@/hooks/chat/useCreatorHistories", () => ({
  useCreatorHistories: (...args: unknown[]) => {
    state.query(...args);
    return state.history;
  },
}));
vi.mock("@/services/conversationService", () => ({
  conversationService: { getById: state.getById },
}));
vi.mock("@/app/newchat/adapter/conversation-thread-list-adapter", () => ({
  RemoteConversationHistoryAdapter: class {
    load() {
      return state.load();
    }
  },
}));
vi.mock("@/app/newchat/adapter/remote-chat-model-adapter", () => ({
  remoteChatModelAdapter: { run: state.run },
}));
vi.mock("@/app/newchat/assistant-ui/chat", () => ({
  Chat: (props: unknown) => {
    state.chat(props);
    return <div>Skill chat</div>;
  },
}));

function panel(targetSkillId: number | null = 8) {
  return (
    <Nl2SkillChatPanel
      targetSkillId={targetSkillId ?? undefined}
      getDraftSnapshot={state.draft}
      onConversationId={state.onId}
      onStreamEvent={state.events}
      language="zh"
      availableFiles={[]}
    />
  );
}
async function send() {
  const result = state.adapter!.run({
    messages: [],
    runConfig: {},
    context: {},
    abortSignal: new AbortController().signal,
  } as never);
  if (Symbol.asyncIterator in result)
    for await (const chunk of result) void chunk;
  else await result;
}
async function openHistory() {
  fireEvent.click(screen.getByRole("button", { name: "历史 2" }));
  fireEvent.click(await screen.findByRole("button", { name: /Skill record/ }));
}
beforeEach(() => {
  vi.clearAllMocks();
  state.threadState.isRunning = false;
  state.history.total = 2;
  state.history.failed = false;
  state.history.hasMore = false;
  state.history.items = [
    { conversation_id: 12, conversation_title: "Skill record", create_time: 1 },
  ];
  state.getById.mockResolvedValue({
    agent_system_key: "nl2skill_main",
    target: { type: "skill", id: 8 },
  });
  state.load.mockResolvedValue({ messages: [{ id: "saved" }] });
  state.runtime.thread.composer.reset.mockResolvedValue(undefined);
});
afterEach(() => message.destroy());

it("shows the current skill's count, shared toolbar title and pagination", async () => {
  state.history.hasMore = true;
  render(panel());
  expect(state.query).toHaveBeenCalledWith("skill", 8);
  fireEvent.click(screen.getByRole("button", { name: "历史 2" }));
  expect(await screen.findByText("此技能的生成记录")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "加载更多" }));
  expect(state.history.loadMore).toHaveBeenCalledOnce();
});

it("keeps unsaved skill history clickable with zero records and supports new conversation", async () => {
  state.history.total = 0;
  state.history.items = [];
  render(panel(null));
  expect(state.query).toHaveBeenCalledWith("skill", null);
  expect(screen.getByRole("button", { name: "历史 0" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "历史 0" }));
  expect(await screen.findByText("暂无历史对话")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "新会话" }));
  await waitFor(() =>
    expect(state.runtime.thread.reset).toHaveBeenCalledOnce()
  );
  expect(state.run).not.toHaveBeenCalled();
  expect(state.onId).toHaveBeenLastCalledWith(undefined);
});

it("restores a saved conversation and continues with the same ID and skill target", async () => {
  render(panel());
  await openHistory();
  await waitFor(() =>
    expect(state.runtime.thread.import).toHaveBeenCalledWith({
      messages: [{ id: "saved" }],
    })
  );
  expect(state.onId).toHaveBeenCalledWith("12");
  await act(send);
  expect(state.run.mock.calls.at(-1)?.[0].runConfig?.custom).toMatchObject({
    runtimeMode: "nl2skill",
    threadId: "12",
    creationTarget: { type: "skill", id: 8 },
    draftSnapshot: state.draft(),
    onNl2SkillEvent: state.events,
  });
  expect(state.history.refresh).toHaveBeenCalled();
});

it("starts a fresh conversation while retaining the skill draft and target", async () => {
  render(panel());
  await openHistory();
  await waitFor(() => expect(state.onId).toHaveBeenCalledWith("12"));
  fireEvent.click(screen.getByRole("button", { name: "新会话" }));
  await waitFor(() =>
    expect(state.runtime.thread.reset).toHaveBeenCalledOnce()
  );
  expect(state.onId).toHaveBeenLastCalledWith(undefined);
  expect(state.run).not.toHaveBeenCalled();
  expect(state.events).not.toHaveBeenCalled();
  await act(send);
  const custom = state.run.mock.calls.at(-1)?.[0].runConfig?.custom;
  expect(custom?.threadId).toBeUndefined();
  expect(custom?.creationTarget).toEqual({ type: "skill", id: 8 });
  expect(custom?.draftSnapshot).toEqual(state.draft());
});

it("remembers server conversation IDs and refreshes the shared history list", async () => {
  render(panel());
  await act(send);
  await act(async () => {
    const onId = state.run.mock.calls.at(-1)?.[0].runConfig?.custom
      ?.onServerConversationId as ((id: string) => void) | undefined;
    onId?.("23");
  });
  expect(state.onId).toHaveBeenLastCalledWith("23");
  await act(send);
  expect(state.run.mock.calls.at(-1)?.[0].runConfig?.custom?.threadId).toBe(
    "23"
  );
});

it("blocks both history controls during generation", () => {
  state.threadState.isRunning = true;
  render(panel());
  expect(screen.getByRole("button", { name: "历史 2" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "新会话" })).toBeDisabled();
});

it.each([
  { agent_system_key: "nl2agent_main", target: { type: "skill", id: 8 } },
  { agent_system_key: "nl2skill_main", target: { type: "skill", id: 99 } },
  { agent_system_key: "nl2skill_main", target: { type: "agent", id: 8 } },
])(
  "rejects another executor or target without clearing the draft",
  async (detail) => {
    state.getById.mockResolvedValue(detail);
    render(panel());
    await openHistory();
    expect(await screen.findByText("恢复对话失败，请重试")).toBeInTheDocument();
    expect(state.runtime.thread.import).not.toHaveBeenCalled();
    expect(state.runtime.thread.reset).not.toHaveBeenCalled();
    expect(state.events).not.toHaveBeenCalled();
  }
);

it("allows retry after list failure", async () => {
  state.history.failed = true;
  render(panel());
  fireEvent.click(screen.getByRole("button", { name: "历史 —" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "历史记录加载失败"
  );
  fireEvent.click(screen.getByRole("button", { name: "重试" }));
  expect(state.history.refetch).toHaveBeenCalled();
});

it("ignores a history load after changing skills", async () => {
  let resolve!: (value: unknown) => void;
  state.getById.mockImplementation(
    () =>
      new Promise((done) => {
        resolve = done;
      })
  );
  const view = render(panel());
  await openHistory();
  view.rerender(panel(99));
  await act(async () => {
    resolve({
      agent_system_key: "nl2skill_main",
      target: { type: "skill", id: 8 },
    });
  });
  expect(state.runtime.thread.import).not.toHaveBeenCalled();
  expect(state.onId).not.toHaveBeenCalled();
});

it("ignores an old run's conversation ID after switching to another skill", async () => {
  const view = render(panel());
  await act(send);
  const onId = state.run.mock.calls.at(-1)?.[0].runConfig?.custom
    ?.onServerConversationId as ((id: string) => void) | undefined;
  view.rerender(panel(99));
  await act(async () => {
    onId?.("old-conversation");
  });
  expect(state.onId).not.toHaveBeenCalled();
  await act(send);
  expect(
    state.run.mock.calls.at(-1)?.[0].runConfig?.custom?.threadId
  ).toBeUndefined();
  expect(
    state.run.mock.calls.at(-1)?.[0].runConfig?.custom?.creationTarget
  ).toEqual({ type: "skill", id: 99 });
});

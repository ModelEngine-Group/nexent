// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, render, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type {
  AssistantRuntime,
  RemoteThreadListAdapter,
} from "@assistant-ui/react";
import { createAssistantStream } from "assistant-stream";
import { beforeEach, expect, it, vi } from "vitest";
import {
  WorkbenchSessionProvider,
  useWorkbenchSession,
} from "@/features/workbench/providers/WorkbenchSessionProvider";

const mocks = vi.hoisted(() => ({
  adapter: null as RemoteThreadListAdapter | null,
}));
vi.mock("@/features/workbench/api", () => ({
  fetchWorkbenchBootstrap: async () => ({ modes: {} }),
}));
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({}),
}));
vi.mock("@/hooks/agent/usePublishedAgentList", () => ({
  usePublishedAgentList: () => ({ agents: [], isLoading: false }),
}));
vi.mock("@/hooks/useConfig", () => ({ useConfig: () => ({}) }));
vi.mock("@/features/workbench/hooks/useConversationRouteGuard", () => ({
  useConversationRouteGuard: vi.fn(),
}));
vi.mock("@/app/newchat/adapter/remote-chat-model-adapter", () => ({
  remoteChatModelAdapter: {
    async *run() {
      yield { content: [{ type: "text", text: "response" }] };
    },
  },
}));
vi.mock("@/app/newchat/adapter/conversation-thread-list-adapter", () => ({
  createConversationThreadListAdapter: () => mocks.adapter,
}));
vi.mock("@/app/newchat/adapter/attachment-adapter", () => ({
  createNewChatAttachmentAdapter: () => undefined,
}));

let runtime: AssistantRuntime;
const metadata = (id: string) => ({
  remoteId: id,
  status: "regular" as const,
  title: `History ${id}`,
});

function Observer() {
  const current = useWorkbenchSession().runtime;
  useEffect(() => {
    runtime = current;
  }, [current]);
  return null;
}

function mount() {
  const query = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={query}>
      <WorkbenchSessionProvider>
        <Observer />
      </WorkbenchSessionProvider>
    </QueryClientProvider>
  );
}

async function expectActive(id: string | undefined) {
  await waitFor(() =>
    expect(runtime.threads.mainItem.getState().remoteId).toBe(id)
  );
}

beforeEach(() => {
  mocks.adapter = {
    async list() {
      return { threads: [metadata("42"), metadata("43")] };
    },
    async fetch(id) {
      return metadata(id);
    },
    async initialize(id) {
      return { remoteId: `workbench-draft:${id}`, externalId: "" };
    },
    async rename() {},
    async archive() {},
    async unarchive() {},
    async delete() {},
    async generateTitle() {
      return createAssistantStream(() => {});
    },
  };
});

it.each(["conversation_id", "thread_id"])(
  "synchronizes selection from a %s deep link and restores the selected conversation on remount",
  async (parameter) => {
    window.history.replaceState(
      { nextState: "preserve" },
      "",
      `/zh/workbench?${parameter}=42&filter=keep#messages`
    );
    const length = window.history.length;
    const view = mount();
    await expectActive("42");
    const initialRuntime = runtime;
    act(() => runtime.thread.composer.setText("Unsent A draft"));

    await act(async () => {
      await runtime.threads.switchToThread("43");
    });
    await expectActive("43");
    expect(window.location.search).toBe("?filter=keep&conversation_id=43");
    expect(window.location.hash).toBe("#messages");
    expect(window.history.state).toEqual({ nextState: "preserve" });
    expect(window.history.length).toBe(length);
    expect(runtime).toBe(initialRuntime);

    await act(async () => {
      await runtime.threads.switchToThread("42");
    });
    await expectActive("42");
    expect(runtime.thread.composer.getState().text).toBe("Unsent A draft");
    expect(
      new URLSearchParams(window.location.search).get("conversation_id")
    ).toBe("42");

    await act(async () => {
      await runtime.threads.switchToThread("43");
    });
    view.unmount();
    mount();
    await expectActive("43");
  }
);

it("clears both saved URL aliases for new and optimistic drafts without replacing their composer", async () => {
  window.history.replaceState(
    {},
    "",
    "/zh/workbench?thread_id=42&conversation_id=43&filter=keep#messages"
  );
  mount();
  await expectActive("42");
  await act(async () => {
    await runtime.threads.switchToNewThread();
  });
  await expectActive(undefined);
  expect(window.location.search).toBe("?filter=keep");
  expect(window.location.hash).toBe("#messages");
  act(() => runtime.thread.composer.setText("Keep optimistic draft"));
  const id = runtime.threads.getState().mainThreadId;
  await act(async () => {
    await runtime.threads.mainItem.initialize();
  });
  await expectActive(`workbench-draft:${id}`);
  expect(window.location.search).toBe("?filter=keep");
  expect(runtime.threads.getState().mainThreadId).toBe(id);
  expect(runtime.thread.composer.getState().text).toBe("Keep optimistic draft");
});

it("keeps the selected conversation, URL and composer through list reorder and metadata reload", async () => {
  window.history.replaceState({}, "", "/zh/workbench?conversation_id=42");
  mount();
  await expectActive("42");
  await act(async () => {
    await runtime.threads.switchToThread("43");
  });
  act(() => runtime.thread.composer.setText("Keep C draft"));
  mocks.adapter!.list = async () => ({
    threads: [metadata("99"), metadata("43"), metadata("42")],
  });

  await act(async () => {
    await runtime.threads.reload();
  });

  await expectActive("43");
  expect(window.location.search).toBe("?conversation_id=43");
  expect(runtime.thread.composer.getState().text).toBe("Keep C draft");
});

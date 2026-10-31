// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, renderHook, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { AssistantRuntime } from "@assistant-ui/react";
import { useConversationResume } from "@/features/workbench/hooks/useConversationResume";

import { createConversationDetailLoader } from "@/lib/conversationDetails";
import { QueryClient } from "@tanstack/react-query";

const service = vi.hoisted(() => ({ getById: vi.fn() }));
vi.mock("@/services/conversationService", () => ({
  CONVERSATION_PAGE_SIZE: 20,
  conversationService: service,
}));
vi.mock(
  "@/app/newchat/adapter/remote-chat-model-adapter",
  async (original) => ({
    ...(await original<object>()),
    remoteChatModelAdapter: { run: vi.fn() },
  })
);
vi.mock("@/lib/logger", () => ({ default: { error: vi.fn(), log: vi.fn() } }));

function conversation() {
  return {
    conversation_id: "13",
    message: [
      { role: "user", message_id: 1, message: "question" },
      { role: "assistant", message_id: 2, message: [], status: "streaming" },
    ],
    streaming_message: { message_id: 2, status: "streaming" },
  };
}

it("UT-FE-WB-003 a late history lookup cannot resume the wrong thread", async () => {
  let finishA!: (value: unknown) => void;
  service.getById.mockReset().mockImplementation((id: string) =>
    id === "12"
      ? new Promise((resolve) => {
          finishA = resolve;
        })
      : Promise.resolve(conversation())
  );
  const resume = vi.fn();
  const runtime = {
    thread: {
      getState: () => ({ isRunning: false }),
      import: vi.fn(),
      resumeRun: resume,
    },
  } as unknown as AssistantRuntime;
  const props = {
    runtime,
    activeConversationId: "12",
    activeThreadId: "a",
    ready: true,
    isThreadRunning: false,
    selectedAgent: null,
    chatMode: "execution" as const,
    resumedConversationIdsRef: { current: new Set<number>() },
    handleGenerationStopped: vi.fn(),
  };
  const { rerender } = renderHook(useConversationResume, {
    initialProps: props,
  });
  rerender({ ...props, activeConversationId: "13", activeThreadId: "b" });
  await waitFor(() => expect(resume).toHaveBeenCalledOnce());
  expect(resume.mock.calls[0][0]).toMatchObject({
    parentId: "1",
    runConfig: { custom: { threadId: "13", resume: true } },
  });
  await act(async () => finishA(conversation()));
  expect(resume).toHaveBeenCalledOnce();
  expect(props.resumedConversationIdsRef.current.has(12)).toBe(false);
});

it.each(["running", "stopped", "restoring"])(
  "UT-FE-WB-003 %s does not trigger duplicate resume",
  (mode) => {
    service.getById.mockReset();
    const resume = vi.fn();
    renderHook(() =>
      useConversationResume({
        runtime: {
          thread: { resumeRun: resume },
        } as unknown as AssistantRuntime,
        activeConversationId: "12",
        activeThreadId: "a",
        ready: mode !== "restoring",
        isThreadRunning: mode === "running",
        selectedAgent: null,
        chatMode: "execution",
        resumedConversationIdsRef: {
          current: new Set(mode === "stopped" ? [12] : []),
        },
        handleGenerationStopped: vi.fn(),
      })
    );
    expect(service.getById).not.toHaveBeenCalled();
    expect(resume).not.toHaveBeenCalled();
  }
);

it("UT-FE-WB-003 returning after a second detach can resume the same conversation again", async () => {
  service.getById.mockReset().mockResolvedValue(conversation());
  const resume = vi.fn();
  const runtime = {
    thread: {
      getState: () => ({ isRunning: false }),
      import: vi.fn(),
      resumeRun: resume,
    },
  } as unknown as AssistantRuntime;
  const props = {
    runtime,
    activeConversationId: "12",
    activeThreadId: "a",
    ready: true,
    isThreadRunning: false,
    selectedAgent: null,
    chatMode: "execution" as const,
    resumedConversationIdsRef: { current: new Set<number>() },
    handleGenerationStopped: vi.fn(),
  };
  const { rerender } = renderHook(useConversationResume, {
    initialProps: props,
  });
  await waitFor(() => expect(resume).toHaveBeenCalledTimes(1));
  rerender({ ...props, activeConversationId: "13", activeThreadId: "b" });
  await waitFor(() => expect(resume).toHaveBeenCalledTimes(2));
  rerender(props);
  await waitFor(() => expect(resume).toHaveBeenCalledTimes(3));
  expect(
    resume.mock.calls.map(([request]) => request.runConfig.custom.threadId)
  ).toEqual(["12", "13", "12"]);
});

it.each(["missing-message", "missing-user", "completed", "lookup-error"])(
  "does not create an orphan for %s",
  async (mode) => {
    const snapshot = conversation();
    if (mode === "missing-message") snapshot.streaming_message.message_id = 99;
    if (mode === "missing-user") snapshot.message.shift();
    if (mode === "completed") snapshot.streaming_message.status = "completed";
    service.getById.mockReset();
    if (mode === "lookup-error")
      service.getById.mockRejectedValue(new Error("offline"));
    else service.getById.mockResolvedValue(snapshot);
    const resumeRun = vi.fn();
    const importHistory = vi.fn();
    renderHook(() =>
      useConversationResume({
        runtime: {
          thread: {
            getState: () => ({ isRunning: false }),
            import: importHistory,
            resumeRun,
          },
        } as unknown as AssistantRuntime,
        activeConversationId: "13",
        activeThreadId: "b",
        ready: true,
        isThreadRunning: false,
        selectedAgent: null,
        chatMode: "execution",
        resumedConversationIdsRef: { current: new Set<number>() },
        handleGenerationStopped: vi.fn(),
      })
    );
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(service.getById).toHaveBeenCalledOnce();
    expect(importHistory).not.toHaveBeenCalled();
    expect(resumeRun).not.toHaveBeenCalled();
  }
);

it.each(["unmounted", "new-run"])(
  "ignores a resolved lookup after %s",
  async (mode) => {
    let resolve!: (value: ReturnType<typeof conversation>) => void;
    service.getById.mockReset().mockImplementation(
      () =>
        new Promise((done) => {
          resolve = done;
        })
    );
    const importHistory = vi.fn();
    const resumeRun = vi.fn();
    let running = false;
    const { unmount } = renderHook(() =>
      useConversationResume({
        runtime: {
          thread: {
            getState: () => ({ isRunning: running }),
            import: importHistory,
            resumeRun,
          },
        } as unknown as AssistantRuntime,
        activeConversationId: "13",
        activeThreadId: "b",
        ready: true,
        isThreadRunning: false,
        selectedAgent: null,
        chatMode: "execution",
        resumedConversationIdsRef: { current: new Set<number>() },
        handleGenerationStopped: vi.fn(),
      })
    );
    if (mode === "unmounted") unmount();
    else running = true;
    await act(async () => {
      resolve(conversation());
    });
    expect(importHistory).not.toHaveBeenCalled();
    expect(resumeRun).not.toHaveBeenCalled();
  }
);

it.each(["completed", "streaming"])(
  "uses shared %s restore state, then reads fresh state after a live run without replaying",
  async (status) => {
    service.getById
      .mockReset()
      .mockResolvedValueOnce({
        ...conversation(),
        streaming_message: { message_id: 2, status },
      })
      .mockResolvedValue({ streaming_message: { status: "completed" } });
    const client = new QueryClient();
    const details = createConversationDetailLoader(client, "resume-test");
    await details.load("12");
    const resume = vi.fn();
    const props = {
      runtime: {
        thread: {
          getState: () => ({ isRunning: false }),
          import: vi.fn(),
          resumeRun: resume,
        },
      } as unknown as AssistantRuntime,
      activeConversationId: "12",
      activeThreadId: "a",
      ready: true,
      isThreadRunning: false,
      selectedAgent: null,
      chatMode: "execution" as const,
      resumedConversationIdsRef: { current: new Set<number>() },
      handleGenerationStopped: vi.fn(),
      loadDetail: details.load,
      invalidateDetail: details.invalidate,
    };
    const { rerender, unmount } = renderHook(useConversationResume, {
      initialProps: props,
    });
    await act(async () => {});
    expect(service.getById).toHaveBeenCalledTimes(1);
    rerender({ ...props, isThreadRunning: true });
    rerender(props);
    await waitFor(() => expect(service.getById).toHaveBeenCalledTimes(2));
    expect(resume).toHaveBeenCalledTimes(status === "streaming" ? 1 : 0);
    unmount();
    client.clear();
  }
);

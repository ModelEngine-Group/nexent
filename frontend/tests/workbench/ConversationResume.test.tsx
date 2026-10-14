import { act, renderHook, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { AssistantRuntime } from "@assistant-ui/react";
import { useConversationResume } from "@/features/workbench/hooks/useConversationResume";

const service = vi.hoisted(() => ({ getById: vi.fn() }));
vi.mock("@/services/conversationService", () => ({
  conversationService: service,
}));
vi.mock("@/app/newchat/adapter/remote-chat-model-adapter", () => ({
  remoteChatModelAdapter: { run: vi.fn() },
}));
vi.mock("@/lib/logger", () => ({ default: { error: vi.fn() } }));

it("UT-FE-WB-003 a late history lookup cannot resume the wrong thread", async () => {
  let finishA!: (value: unknown) => void;
  service.getById.mockReset().mockImplementation((id: string) =>
    id === "12"
      ? new Promise((resolve) => {
          finishA = resolve;
        })
      : Promise.resolve({ streaming_message: { status: "streaming" } })
  );
  const resume = vi.fn();
  const runtime = {
    thread: {
      getState: () => ({ messages: [{ id: "last-b" }] }),
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
    parentId: "last-b",
    runConfig: { custom: { threadId: "13", resume: true } },
  });
  await act(async () =>
    finishA({ streaming_message: { status: "streaming" } })
  );
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
  service.getById
    .mockReset()
    .mockResolvedValue({ streaming_message: { status: "streaming" } });
  const resume = vi.fn();
  const runtime = {
    thread: { getState: () => ({ messages: [] }), resumeRun: resume },
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

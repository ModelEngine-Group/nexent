// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { renderHook, act } from "@testing-library/react";
import type { AssistantRuntime } from "@assistant-ui/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useCreationModeConfirmation } from "@/features/workbench/hooks/useCreationModeConfirmation";
import { confirmWorkbenchCreationMode } from "@/features/workbench/api";
import { parseClarification } from "@/lib/clarification";
import type { ClarificationResponse } from "@/types/clarification";
import type { WorkbenchMode } from "@/features/workbench/types";
import { initializeTestI18n } from "./i18n";

vi.mock("@/features/workbench/api", () => ({
  confirmWorkbenchCreationMode: vi.fn(),
}));
const response: ClarificationResponse = {
  schema_version: 1,
  unit_index: 7,
  form: parseClarification({
    schema_version: 1,
    questions: [
      {
        id: "workbench_creation_mode",
        type: "single_choice",
        title: "进入创建？",
        creation_request: "整理多轮讨论的论文，保留出处，输出中文摘要。",
        options: [
          { id: "agent_create", label: "智能体创建" },
          { id: "continue_chat", label: "继续对话" },
        ],
      },
    ],
  })!,
  answers: [
    {
      questionId: "workbench_creation_mode",
      value: "agent_create",
      otherText: null,
    },
  ],
};
beforeEach(async () => {
  await initializeTestI18n();
  vi.mocked(confirmWorkbenchCreationMode)
    .mockReset()
    .mockResolvedValue({
      message_id: 20,
      mode: "agent_create",
      clarification_response: {
        ...response,
        source_message_id: 10,
        unit_index: 7,
      },
    });
});

function setup() {
  const state = {
    threadId: "ordinary",
    running: false,
    disabled: false,
    messageId: "proposal",
  };
  const append = vi.fn();
  const setText = vi.fn();
  const source = {
    getState: () => ({
      isRunning: state.running,
      isDisabled: state.disabled,
      messages: [{ id: state.messageId }],
    }),
    append,
  };
  const runtime = {
    threads: {
      getState: () => ({ mainThreadId: state.threadId }),
      getById: () => source,
    },
    thread: { composer: { setText } },
  } as unknown as AssistantRuntime;
  const changeMode = vi.fn(async () => {
    state.threadId = "creation";
    return true;
  });
  const options = {
    runtime,
    conversationId: "42",
    mode: "generic_chat" as WorkbenchMode,
    canCreateAgent: true,
    canCreateSkill: true,
    changeMode,
    onSaved: vi.fn(),
  };
  const view = renderHook((props) => useCreationModeConfirmation(props), {
    initialProps: options,
  });
  const request = {
    threadId: "ordinary",
    messageId: "proposal",
    originalRequest: "就按刚才讨论的来一个",
    response,
  };
  return {
    ...view,
    state,
    source,
    append,
    setText,
    changeMode,
    options,
    request,
  };
}

it("persists before changing mode, appends without generation and carries the AI context", async () => {
  const test = setup();
  await act(() => test.result.current.confirm(test.request));
  expect(confirmWorkbenchCreationMode).toHaveBeenCalledExactlyOnceWith(
    42,
    response
  );
  expect(test.changeMode).toHaveBeenCalledExactlyOnceWith("agent_create");
  expect(test.append).toHaveBeenCalledWith(
    expect.objectContaining({ role: "user", startRun: false })
  );
  expect(test.setText.mock.calls[0][0]).toContain(
    response.form.questions[0].creation_request
  );
  expect(test.setText.mock.calls[0][0]).toContain(test.request.originalRequest);
  expect(
    vi.mocked(confirmWorkbenchCreationMode).mock.invocationCallOrder[0]
  ).toBeLessThan(test.changeMode.mock.invocationCallOrder[0]);
});

it.each(["permission", "running", "stale", "thread", "disabled"])(
  "rejects %s before persistence or navigation",
  async (reason) => {
    const test = setup();
    if (reason === "permission")
      test.rerender({ ...test.options, canCreateAgent: false });
    if (reason === "running") test.state.running = true;
    if (reason === "stale") test.state.messageId = "newer";
    if (reason === "thread") test.state.threadId = "other";
    if (reason === "disabled") test.state.disabled = true;
    await expect(test.result.current.confirm(test.request)).rejects.toThrow();
    expect(confirmWorkbenchCreationMode).not.toHaveBeenCalled();
    expect(test.changeMode).not.toHaveBeenCalled();
  }
);

it("a failed save keeps the original mode and draft and permits retry", async () => {
  const test = setup();
  vi.mocked(confirmWorkbenchCreationMode).mockRejectedValueOnce(
    new Error("Save failed")
  );
  await expect(test.result.current.confirm(test.request)).rejects.toThrow(
    "Save failed"
  );
  expect(test.changeMode).not.toHaveBeenCalled();
  expect(test.append).not.toHaveBeenCalled();
  expect(test.setText).not.toHaveBeenCalled();
  await act(() => test.result.current.confirm(test.request));
  expect(test.changeMode).toHaveBeenCalledTimes(1);
});

it("a failed transition reuses its saved receipt on retry", async () => {
  const test = setup();
  test.changeMode.mockResolvedValueOnce(false);
  await expect(test.result.current.confirm(test.request)).rejects.toThrow();
  expect(test.append).not.toHaveBeenCalled();
  await act(() => test.result.current.confirm(test.request));
  expect(confirmWorkbenchCreationMode).toHaveBeenCalledTimes(1);
  expect(test.changeMode).toHaveBeenCalledTimes(2);
});

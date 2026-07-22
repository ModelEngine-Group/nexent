import React from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  type Nl2AgentContinuationRequest,
  Nl2AgentWorkflowProvider,
  useNl2AgentWorkflow,
} from "../Nl2AgentWorkflowContext";
import { useNl2AgentCardLifecycle } from "../useNl2AgentCardLifecycle";

const wrapperFor = (
  onContinue: (request: Nl2AgentContinuationRequest) => Promise<void>
) =>
  function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <Nl2AgentWorkflowProvider
        enabled
        scopeKey="conversation:1:draft:54"
        onContinue={onContinue}
      >
        {children}
      </Nl2AgentWorkflowProvider>
    );
  };

const useLifecycleWithWorkflow = () => ({
  lifecycle: useNl2AgentCardLifecycle("models:54"),
  workflow: useNl2AgentWorkflow(),
});

describe("useNl2AgentCardLifecycle", () => {
  it("balances busy state and triggers continuation after success", async () => {
    const onContinue = vi.fn(async () => undefined);
    let resolveAction:
      ((value: { chat_injection_text: string }) => void) | undefined;
    const action = vi.fn(
      () =>
        new Promise<{ chat_injection_text: string }>((resolve) => {
          resolveAction = resolve;
        })
    );
    const { result } = renderHook(useLifecycleWithWorkflow, {
      wrapper: wrapperFor(onContinue),
    });

    let execution: Promise<unknown> | undefined;
    act(() => {
      execution = result.current.lifecycle.execute(action, {
        blockInput: true,
        continuationText: (value) => value.chat_injection_text,
      });
    });
    expect(result.current.lifecycle.pending).toBe(true);
    expect(result.current.workflow.busy).toBe(true);

    await act(async () => {
      resolveAction?.({ chat_injection_text: "[[NL2AGENT_AUTO_CONTINUE]]" });
      await execution;
    });

    expect(result.current.lifecycle.pending).toBe(false);
    expect(result.current.workflow.busy).toBe(false);
    expect(onContinue).toHaveBeenCalledOnce();
    expect(onContinue).toHaveBeenCalledWith({
      kind: "automatic",
      text: "[[NL2AGENT_AUTO_CONTINUE]]",
    });
  });

  it("records a successful card action as a structured user continuation", async () => {
    vi.stubGlobal("crypto", { randomUUID: () => "action-123" });
    const onContinue = vi.fn(async () => undefined);
    const action = vi.fn(async () => ({
      chat_injection_text: "[[NL2AGENT_AUTO_CONTINUE]] models saved",
      modelNames: ["GPT-5", "Embedding V3"],
    }));
    const { result } = renderHook(useLifecycleWithWorkflow, {
      wrapper: wrapperFor(onContinue),
    });

    await act(async () => {
      await result.current.lifecycle.execute(action, {
        continuationText: (value) => value.chat_injection_text,
        userAction: (value) => ({
          action: "save_model_selection",
          displayText: `Saved models: ${value.modelNames.join(", ")}`,
        }),
      });
    });

    expect(onContinue).toHaveBeenCalledWith({
      kind: "user_action",
      text: "[[NL2AGENT_AUTO_CONTINUE]] models saved",
      action: {
        actionId: "action-123",
        action: "save_model_selection",
        displayText: "Saved models: GPT-5, Embedding V3",
      },
    });
    vi.unstubAllGlobals();
  });

  it("does not record a user action when the card operation fails", async () => {
    const onContinue = vi.fn(async () => undefined);
    const action = vi.fn(async () => {
      throw new Error("save failed");
    });
    const { result } = renderHook(useLifecycleWithWorkflow, {
      wrapper: wrapperFor(onContinue),
    });

    await act(async () => {
      await expect(
        result.current.lifecycle.execute(action, {
          continuationText: () => "[[NL2AGENT_AUTO_CONTINUE]]",
          userAction: () => ({
            action: "save_model_selection",
            displayText: "Saved models",
          }),
        })
      ).rejects.toThrow("save failed");
    });

    expect(onContinue).not.toHaveBeenCalled();
  });

  it("keeps a failed action retryable", async () => {
    const action = vi
      .fn<() => Promise<{ ok: boolean }>>()
      .mockRejectedValueOnce(new Error("temporary failure"))
      .mockResolvedValueOnce({ ok: true });
    const { result } = renderHook(useLifecycleWithWorkflow, {
      wrapper: wrapperFor(vi.fn(async () => undefined)),
    });

    await act(async () => {
      await expect(result.current.lifecycle.execute(action)).rejects.toThrow(
        "temporary failure"
      );
    });
    expect(result.current.lifecycle.error).toBe("temporary failure");

    await act(async () => {
      await result.current.lifecycle.retry();
    });
    await waitFor(() => expect(action).toHaveBeenCalledTimes(2));
    expect(result.current.lifecycle.error).toBeUndefined();
  });

  it("retains an input blocker after registration failure until retry succeeds", async () => {
    const action = vi
      .fn<() => Promise<{ ok: boolean }>>()
      .mockRejectedValueOnce(new Error("registration unavailable"))
      .mockResolvedValueOnce({ ok: true });
    const { result } = renderHook(useLifecycleWithWorkflow, {
      wrapper: wrapperFor(vi.fn(async () => undefined)),
    });

    await act(async () => {
      await expect(
        result.current.lifecycle.execute(action, {
          blockInput: true,
          retainInputBlockOnError: true,
        })
      ).rejects.toThrow("registration unavailable");
    });
    expect(result.current.workflow.busy).toBe(true);

    await act(async () => {
      await result.current.lifecycle.retry();
    });
    expect(result.current.workflow.busy).toBe(false);
  });

  it("releases an input blocker for a deterministic registration failure", async () => {
    const conflict = new Error("workflow conflict");
    const action = vi.fn<() => Promise<never>>().mockRejectedValue(conflict);
    const { result } = renderHook(useLifecycleWithWorkflow, {
      wrapper: wrapperFor(vi.fn(async () => undefined)),
    });

    await act(async () => {
      await expect(
        result.current.lifecycle.execute(action, {
          blockInput: true,
          retainInputBlockOnError: (error) => error !== conflict,
        })
      ).rejects.toThrow("workflow conflict");
    });

    expect(result.current.workflow.busy).toBe(false);
  });
});

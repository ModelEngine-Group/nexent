import React from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  Nl2AgentWorkflowProvider,
  useNl2AgentWorkflow,
} from "../Nl2AgentWorkflowContext";
import { useNl2AgentCardLifecycle } from "../useNl2AgentCardLifecycle";

const wrapperFor = (onContinue: (text: string) => Promise<void>) =>
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
});

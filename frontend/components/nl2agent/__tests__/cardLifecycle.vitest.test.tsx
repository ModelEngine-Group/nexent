import React from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  dispatchNl2AgentAction,
  getNl2AgentSessionState,
  type Nl2AgentActionDraft,
} from "@/services/nl2agentService";
import {
  type Nl2AgentContinuationRequest,
  Nl2AgentWorkflowProvider,
  useNl2AgentWorkflow,
} from "../Nl2AgentWorkflowContext";
import { useNl2AgentCardLifecycle } from "../useNl2AgentCardLifecycle";

vi.mock("@/services/nl2agentService", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/services/nl2agentService")>()),
  dispatchNl2AgentAction: vi.fn(),
  getNl2AgentSessionState: vi.fn(),
}));

const action: Nl2AgentActionDraft = {
  action: "save_identity",
  display_text: "Agent name saved: Research Agent",
  payload: { display_name: "Research Agent" },
};

const wrapperFor = (
  onContinue: (request: Nl2AgentContinuationRequest) => Promise<void>
) =>
  function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <Nl2AgentWorkflowProvider
        enabled
        agentId={54}
        scopeKey="conversation:1:draft:54"
        onContinue={onContinue}
      >
        {children}
      </Nl2AgentWorkflowProvider>
    );
  };

const useLifecycleWithWorkflow = () => ({
  lifecycle: useNl2AgentCardLifecycle("identity:54"),
  workflow: useNl2AgentWorkflow(),
});

describe("useNl2AgentCardLifecycle", () => {
  beforeEach(() => {
    vi.mocked(getNl2AgentSessionState).mockReset();
    vi.mocked(getNl2AgentSessionState).mockResolvedValue({
      agent_id: 54,
      revision: 18,
      models: [],
      tools: [],
      skills: [],
      local_tool_parameter_schemas: {},
      invalid_references: [],
      resource_review: { recommendations: {}, mcp_workflows: {} },
    } as never);
    vi.mocked(dispatchNl2AgentAction).mockReset();
  });

  it("dispatches one revision-bound action and continues with its durable context", async () => {
    vi.stubGlobal("crypto", { randomUUID: () => "action-123" });
    const onContinue = vi.fn(async () => undefined);
    vi.mocked(dispatchNl2AgentAction).mockResolvedValue({
      action_id: "action-123",
      action: "save_identity",
      status: "applied",
      workflow_revision: 19,
      result: { display_name: "Research Agent" },
    });
    const { result } = renderHook(useLifecycleWithWorkflow, {
      wrapper: wrapperFor(onContinue),
    });
    await waitFor(() =>
      expect(result.current.workflow.sessionState).toBeTruthy()
    );

    await act(async () => {
      await result.current.lifecycle.execute(action);
    });

    expect(dispatchNl2AgentAction).toHaveBeenCalledWith(54, {
      ...action,
      action_id: "action-123",
      expected_revision: 18,
    });
    expect(onContinue).toHaveBeenCalledWith({
      kind: "action",
      context: {
        actionId: "action-123",
        action: "save_identity",
        displayText: "Agent name saved: Research Agent",
        workflowRevision: 19,
      },
    });
    vi.unstubAllGlobals();
  });

  it("keeps the same action_id when a failed request is retried", async () => {
    vi.stubGlobal("crypto", { randomUUID: () => "stable-action" });
    vi.mocked(dispatchNl2AgentAction)
      .mockRejectedValueOnce(new Error("temporary failure"))
      .mockResolvedValueOnce({
        action_id: "stable-action",
        action: "save_identity",
        status: "replayed",
        workflow_revision: 19,
        result: {},
      });
    const { result } = renderHook(useLifecycleWithWorkflow, {
      wrapper: wrapperFor(vi.fn(async () => undefined)),
    });
    await waitFor(() =>
      expect(result.current.workflow.sessionState).toBeTruthy()
    );

    await act(async () => {
      await expect(result.current.lifecycle.execute(action)).rejects.toThrow(
        "temporary failure"
      );
    });
    await act(async () => {
      await result.current.lifecycle.execute(action, {
        continueAfterSuccess: false,
      });
    });

    expect(dispatchNl2AgentAction).toHaveBeenCalledTimes(2);
    expect(vi.mocked(dispatchNl2AgentAction).mock.calls[0][1].action_id).toBe(
      "stable-action"
    );
    expect(vi.mocked(dispatchNl2AgentAction).mock.calls[1][1].action_id).toBe(
      "stable-action"
    );
    vi.unstubAllGlobals();
  });

  it("balances pending and busy state while a dispatch is in flight", async () => {
    let resolveAction: ((value: never) => void) | undefined;
    vi.mocked(dispatchNl2AgentAction).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveAction = resolve as (value: never) => void;
        })
    );
    const { result } = renderHook(useLifecycleWithWorkflow, {
      wrapper: wrapperFor(vi.fn(async () => undefined)),
    });
    await waitFor(() =>
      expect(result.current.workflow.sessionState).toBeTruthy()
    );

    let execution: Promise<unknown> | undefined;
    act(() => {
      execution = result.current.lifecycle.execute(action, {
        blockInput: true,
        continueAfterSuccess: false,
      });
    });
    expect(result.current.lifecycle.pending).toBe(true);
    expect(result.current.workflow.busy).toBe(true);

    await act(async () => {
      resolveAction?.({
        action_id: "action-1",
        action: "save_identity",
        status: "applied",
        workflow_revision: 19,
        result: {},
      } as never);
      await execution;
    });
    expect(result.current.lifecycle.pending).toBe(false);
    expect(result.current.workflow.busy).toBe(false);
  });

  it("surfaces a failed structured continuation without hidden retries", async () => {
    const onContinue = vi.fn(async () => {
      throw new Error("continuation unavailable");
    });
    const { result } = renderHook(useLifecycleWithWorkflow, {
      wrapper: wrapperFor(onContinue),
    });

    await act(async () => {
      await expect(
        result.current.workflow.continueWithAction({
          actionId: "action-1",
          action: "save_identity",
          displayText: "Saved",
          workflowRevision: 19,
        })
      ).rejects.toThrow("continuation unavailable");
    });

    expect(onContinue).toHaveBeenCalledTimes(1);
  });
});

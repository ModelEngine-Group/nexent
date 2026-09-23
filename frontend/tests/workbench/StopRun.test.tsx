import { act, renderHook } from "@testing-library/react";
import type { AssistantRuntime } from "@assistant-ui/react";
import { expect, it, vi } from "vitest";
import { useRunMessageQueue } from "@/features/humanInteraction/useRunMessageQueue";
import type { HumanInteractionController } from "@/features/humanInteraction/useHumanInteractionController";

function setup(running: boolean, active: boolean) {
  const cancelRun = vi.fn();
  const control = vi.fn().mockResolvedValue(undefined);
  const runtime = {
    thread: {
      getState: () => ({ isRunning: running, messages: [] }),
      cancelRun,
    },
  } as unknown as AssistantRuntime;
  const controller = {
    active,
    streaming: running,
    run: null,
    control,
  } as unknown as HumanInteractionController;
  const { result } = renderHook(() =>
    useRunMessageQueue({ scope: "conversation-12", runtime, controller })
  );
  return { result, cancelRun, control };
}

it("stops an active Workbench stream locally and through its abort handler with one click", async () => {
  const { result, cancelRun, control } = setup(true, true);
  await act(async () => result.current.stop());
  expect(cancelRun).toHaveBeenCalledOnce();
  expect(control).not.toHaveBeenCalled();
});

it("stops a streaming Agent chat even before a HITL run is discovered", async () => {
  const { result, cancelRun, control } = setup(true, false);
  await act(async () => result.current.stop());
  expect(cancelRun).toHaveBeenCalledOnce();
  expect(control).not.toHaveBeenCalled();
});

it("terminates a paused HITL run when no local stream is active", async () => {
  const { result, cancelRun, control } = setup(false, true);
  await act(async () => result.current.stop());
  expect(control).toHaveBeenCalledExactlyOnceWith("terminate");
  expect(cancelRun).not.toHaveBeenCalled();
});

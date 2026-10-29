// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { App } from "antd";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
const api = vi.hoisted(() => ({
  getConversationModelSelection: vi.fn(),
  patchConversationModelSelection: vi.fn(),
}));
vi.mock("@/services/modelProfileService", () => api);
let selected = 2;
beforeEach(() => {
  vi.resetAllMocks();
  selected = 2;
  api.getConversationModelSelection.mockImplementation(async () => ({
    selected_model_id: selected,
    version: 4,
  }));
  api.patchConversationModelSelection.mockImplementation(
    async (_id, modelId) => ({
      selected_model_id: (selected = modelId),
      version: 5,
    })
  );
});
function Wrapper({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: false },
          mutations: { retry: false },
        },
      })
  );
  return (
    <App>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </App>
  );
}
import { useConversationModelControls } from "@/features/model-controls/useConversationModelControls";
import { rejectModelSelection } from "@/features/model-controls/rejectedSelection";
import type { ModelOption } from "@/app/newchat/ui/model-selector";
import { ConversationModelControlsProvider } from "@/features/model-controls/ConversationModelControlsProvider";

const models: ModelOption[] = [
  { id: "1", name: "A", profileSchemaVersion: 1 },
  { id: "2", name: "B", profileSchemaVersion: 1 },
];

it("SU-AC-01 selects a model without creating a second parameter state", () => {
  const { result } = renderHook(
    () => useConversationModelControls(models, "select"),
    { wrapper: Wrapper }
  );
  expect(result.current.snapshot).toEqual({ model_id: 1 });
  expect(result.current).not.toHaveProperty("modelParameterSettings");
  expect(result.current).not.toHaveProperty("deepThinking");
  act(() => result.current.onModelChange("2"));
  expect(result.current.snapshot).toEqual({ model_id: 2 });
});

it("SU-AC-04 isolates selections by thread and keeps explicit choices through delayed defaults", () => {
  const { result, rerender } = renderHook(
    ({ scope }) => useConversationModelControls(models, scope, "1"),
    { initialProps: { scope: "a" }, wrapper: Wrapper }
  );
  act(() => result.current.onModelChange("2"));
  rerender({ scope: "a" });
  expect(result.current.selectedModelId).toBe("2");
  rerender({ scope: "b" });
  expect(result.current.selectedModelId).toBe("1");
  rerender({ scope: "a" });
  expect(result.current.selectedModelId).toBe("2");
});

it("SU-AC-05 rejects unavailable selections and never silently changes a removed explicit model", () => {
  const { result, rerender } = renderHook(
    ({ options }) => useConversationModelControls(options, "rejected"),
    { initialProps: { options: models }, wrapper: Wrapper }
  );
  act(() => rejectModelSelection(1));
  expect(result.current.canSend).toBe(false);
  act(() => result.current.onModelChange("2"));
  expect(result.current.canSend).toBe(true);
  rerender({ options: [models[0]] });
  expect(result.current.selectedModelId).toBe("2");
  expect(result.current.canSend).toBe(false);
  expect(result.current.snapshot).toBeUndefined();
  act(() => result.current.onModelChange("999"));
  expect(result.current.selectedModelId).toBe("2");
});

it.each(["agent", "workbench"])(
  "SU-AC-01 restores and saves selection through the shared preference API (%s)",
  async (mode) => {
    const { result, unmount } = renderHook(
      () => useConversationModelControls(models, mode, "1", undefined, 123),
      { wrapper: Wrapper }
    );
    expect(result.current.canSend).toBe(false);
    await waitFor(() => expect(result.current.selectedModelId).toBe("2"));
    expect(result.current.canSend).toBe(true);
    act(() => result.current.onModelChange("1"));
    await waitFor(() =>
      expect(api.patchConversationModelSelection).toHaveBeenCalledWith(
        123,
        1,
        4
      )
    );
    await waitFor(() => expect(result.current.selectedModelId).toBe("1"));
    unmount();
    const restored = renderHook(
      () =>
        useConversationModelControls(
          models,
          `${mode}-refresh`,
          "2",
          undefined,
          123
        ),
      { wrapper: Wrapper }
    );
    await waitFor(() => expect(restored.result.current.canSend).toBe(true));
    expect(restored.result.current.selectedModelId).toBe("1");
  }
);

it("SU-AC-05 keeps server selection after CAS rejection and blocks running when restoration fails", async () => {
  api.patchConversationModelSelection.mockRejectedValueOnce(
    new Error("conflict")
  );
  const { result } = renderHook(
    () => useConversationModelControls(models, "conflict", "1", undefined, 123),
    { wrapper: Wrapper }
  );
  await waitFor(() => expect(result.current.selectedModelId).toBe("2"));
  act(() => result.current.onModelChange("1"));
  await waitFor(() =>
    expect(api.patchConversationModelSelection).toHaveBeenCalled()
  );
  await waitFor(() => expect(result.current.canSend).toBe(true));
  expect(result.current.selectedModelId).toBe("2");
  api.getConversationModelSelection.mockRejectedValueOnce(
    new Error("forbidden")
  );
  const failed = renderHook(
    () => useConversationModelControls(models, "denied", "1", undefined, 124),
    { wrapper: Wrapper }
  );
  await waitFor(() =>
    expect(api.getConversationModelSelection).toHaveBeenCalledWith(
      124,
      expect.anything()
    )
  );
  expect(failed.result.current.canSend).toBe(false);
});

it("SU-AC-03 restores an unsent thread selection after its UI unmounts", () => {
  const first = renderHook(
    () => useConversationModelControls(models, "unsent-return", "1"),
    { wrapper: Wrapper }
  );
  act(() => first.result.current.onModelChange("2"));
  first.unmount();
  const other = renderHook(
    () => useConversationModelControls(models, "unsent-other", "1"),
    { wrapper: Wrapper }
  );
  expect(other.result.current.selectedModelId).toBe("1");
  other.unmount();
  const restored = renderHook(
    () => useConversationModelControls(models, "unsent-return", "1"),
    { wrapper: Wrapper }
  );
  expect(restored.result.current.selectedModelId).toBe("2");
  expect(api.patchConversationModelSelection).not.toHaveBeenCalled();
});

it("SU-AC-04 exposes a recovery message for an unavailable saved selection", async () => {
  api.getConversationModelSelection.mockResolvedValueOnce({
    selected_model_id: 999,
    version: 4,
  });
  const { result } = renderHook(
    () =>
      useConversationModelControls(
        models,
        "invalid-saved",
        "1",
        undefined,
        125
      ),
    { wrapper: Wrapper }
  );
  await waitFor(() =>
    expect(result.current.error).toBe("modelProfile.modelUnavailable")
  );
  expect(result.current.canSend).toBe(false);
  expect(result.current.selectedModelId).toBe("999");
});

it.each(["unavailable", "not_detected"])(
  "AC-FIX-03 requires a manual choice for a new %s outlet and keeps it across remounts",
  (status) => {
    const options: ModelOption[] = [
      {
        id: "42",
        name: "Explicit",
        profileSchemaVersion: 1,
        connectStatus: status,
      },
    ];
    const scope = `manual-${status}`;
    const first = renderHook(
      () => useConversationModelControls(options, scope),
      { wrapper: Wrapper }
    );
    expect(first.result.current.selectedModelId).toBeUndefined();
    expect(first.result.current.canSend).toBe(false);
    act(() => first.result.current.onModelChange("42"));
    expect(first.result.current.canSend).toBe(true);
    expect(first.result.current.snapshot).toEqual({ model_id: 42 });
    first.unmount();
    const restored = renderHook(
      () => useConversationModelControls(options, scope),
      { wrapper: Wrapper }
    );
    expect(restored.result.current.selectedModelId).toBe("42");
    expect(restored.result.current.canSend).toBe(true);
    expect(options[0].connectStatus).toBe(status);
  }
);

it.each(["agent", "workbench"])(
  "AC-FIX-03 restores an explicitly saved failed selection for %s",
  async (mode) => {
    const options: ModelOption[] = [
      {
        id: "2",
        name: "Saved",
        profileSchemaVersion: 1,
        connectStatus: "unavailable",
      },
    ];
    const { result } = renderHook(
      () =>
        useConversationModelControls(
          options,
          `saved-failed-${mode}`,
          undefined,
          undefined,
          123
        ),
      { wrapper: Wrapper }
    );
    await waitFor(() => expect(result.current.selectedModelId).toBe("2"));
    expect(result.current.canSend).toBe(true);
    expect(result.current.snapshot).toEqual({ model_id: 2 });
    expect(options[0].connectStatus).toBe("unavailable");
  }
);

// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useConversationModelControls } from "@/features/model-controls/useConversationModelControls";
import { snapshotTurnModelControls } from "@/features/model-controls/turnControls";
import { rejectModelSelection } from "@/features/model-controls/rejectedSelection";
import type { ModelOption } from "@/app/newchat/ui/model-selector";

const models: ModelOption[] = [
  {
    id: "1",
    name: "A",
    defaultEffort: "low",
    defaultDeepThinking: false,
    efforts: ["auto", "low", "xhigh"].map((id) => ({ id, name: id })),
  },
  {
    id: "2",
    name: "B",
    defaultEffort: "xhigh",
    defaultDeepThinking: true,
    efforts: ["auto", "xhigh"].map((id) => ({ id, name: id })),
  },
];

describe("shared conversation model controls", () => {
  it("re-enabling thinking restores current configured effort and budget, not temporary values", () => {
    const { result, rerender } = renderHook(
      ({ options }) => useConversationModelControls(options, "reset"),
      { initialProps: { options: models } }
    );
    act(() => result.current.onDeepThinkingChange(true));
    act(() => result.current.onThinkingEffortChange("xhigh"));
    act(() => result.current.onDeepThinkingChange(false));
    expect(result.current.snapshot?.generation_config).toMatchObject({
      deep_thinking: false,
    });
    rerender({ options: [{ ...models[0], defaultEffort: "auto" }, models[1]] });
    act(() => result.current.onDeepThinkingChange(true));
    expect(result.current.thinkingEffort).toBe("auto");
    const budget = renderHook(() =>
      useConversationModelControls(
        [
          {
            id: "3",
            name: "Budget",
            budgetTokens: { min: 1024, max: 8192 },
            defaultBudgetTokens: 2048,
          },
        ],
        "budget-reset"
      )
    );
    act(() => budget.result.current.onDeepThinkingChange(true));
    act(() => budget.result.current.onReasoningBudgetTokensChange(4096));
    act(() => budget.result.current.onDeepThinkingChange(false));
    act(() => budget.result.current.onDeepThinkingChange(true));
    expect(budget.result.current.reasoningBudgetTokens).toBe(2048);
  });

  it("blocks a rejected selection until explicit reselection and retains explicit sampling in immutable run controls", () => {
    const { result, rerender } = renderHook(
      ({ key }) => useConversationModelControls(models, key),
      { initialProps: { key: "first" } }
    );
    const first = result.current.snapshot;
    rerender({ key: "first" });
    expect(result.current.snapshot).toBe(first);
    act(() =>
      result.current.modelParameterSettings.onChange({
        temperature: 0.7,
        top_p: 1,
      })
    );
    act(() => rejectModelSelection(1));
    expect(result.current.canSend).toBe(false);
    expect(result.current.modelParameterSettings.value).toEqual({
      temperature: 0.7,
      top_p: 1,
    });
    act(() => result.current.onModelChange("2"));
    expect(result.current.canSend).toBe(true);
    expect(
      result.current.modelParameterSettings.value.temperature
    ).toBeUndefined();
    act(() => result.current.onModelChange("1"));
    expect(result.current.canSend).toBe(true);
    expect(result.current.modelParameterSettings.value.temperature).toBe(0.7);
    expect(result.current.snapshot?.generation_config).toMatchObject({
      temperature: 0.7,
      top_p: 1,
    });
    rerender({ key: "second" });
    expect(
      result.current.modelParameterSettings.value.temperature
    ).toBeUndefined();
  });
  it("keeps explicit selection through delayed defaults and preserves per-model reasoning", () => {
    const { result, rerender } = renderHook(
      ({ defaultId }) =>
        useConversationModelControls(models, "session-a", defaultId),
      { initialProps: { defaultId: "1" } }
    );
    act(() => result.current.onModelChange("2"));
    act(() => result.current.onDeepThinkingChange(false));
    rerender({ defaultId: "1" });
    expect(result.current.selectedModelId).toBe("2");
    expect(result.current.deepThinking).toBe(false);
    act(() => result.current.onModelChange("1"));
    act(() => result.current.onDeepThinkingChange(true));
    act(() => result.current.onThinkingEffortChange("xhigh"));
    act(() => result.current.onModelChange("2"));
    expect(result.current.deepThinking).toBe(false);
    act(() => result.current.onModelChange("1"));
    expect(result.current.snapshot).toEqual({
      model_id: 1,
      generation_config: { deep_thinking: true, thinking_effort: "xhigh" },
    });
  });

  it("isolates thread/user scopes and never falls back for a removed explicit model", () => {
    const { result, rerender } = renderHook(
      ({ key, options }) => useConversationModelControls(options, key, "1"),
      { initialProps: { key: "tenant-a:user-a:thread-a", options: models } }
    );
    act(() => result.current.onModelChange("2"));
    const firstSnapshot = result.current.snapshot;
    rerender({ key: "tenant-a:user-a:thread-b", options: models });
    expect(result.current.selectedModelId).toBe("1");
    rerender({ key: "tenant-a:user-a:thread-a", options: [models[0]] });
    expect(result.current.selectedModelId).toBe("2");
    expect(result.current.canSend).toBe(false);
    expect(result.current.snapshot).toBeUndefined();
    expect(firstSnapshot?.model_id).toBe(2);
    rerender({ key: "tenant-b:user-b:thread-a", options: models });
    expect(result.current.selectedModelId).toBe("1");
  });

  it("resolves stale effort and budget to capabilities without fabricating generic levels", () => {
    const budgetModel: ModelOption = {
      id: "3",
      name: "budget",
      budgetTokens: { min: 1024, max: 4096 },
    };
    const { result } = renderHook(() =>
      useConversationModelControls([budgetModel], "budget-session")
    );
    expect(result.current.snapshot?.generation_config).toMatchObject({
      thinking_effort: "auto",
      reasoning_budget_tokens: 0,
    });
    act(() => result.current.onReasoningBudgetTokensChange(8000));
    expect(result.current.reasoningBudgetTokens).toBe(4096);
    const plain = renderHook(() =>
      useConversationModelControls(
        [{ id: "4", name: "plain" }],
        "plain-session"
      )
    );
    act(() => plain.result.current.onDeepThinkingChange(true));
    expect(plain.result.current.deepThinking).toBe(false);
    expect(plain.result.current.models[0].efforts).toBeUndefined();
  });

  it("snapshots only canonical runtime controls and keeps copied intent immutable", () => {
    const values = {
      deep_thinking: true,
      thinking_effort: "xhigh" as const,
      temperature: 0.7,
      top_p: 0,
    };
    const snapshot = snapshotTurnModelControls(2, values);
    values.deep_thinking = false;
    expect(snapshot).toEqual({
      model_id: 2,
      generation_config: {
        deep_thinking: true,
        thinking_effort: "xhigh",
        temperature: 0.7,
        top_p: 0,
      },
    });
    for (const id of [0, -1, 1.5, "main_model"])
      expect(() => snapshotTurnModelControls(id, {})).toThrow(
        "model_not_available"
      );
  });
});

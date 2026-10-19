// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useMemo, useState } from "react";
import type { ModelOption } from "@/app/newchat/ui/model-selector";
import type { ReasoningEffort } from "@/types/modelConfig";
import { isReasoningEffort } from "@/lib/modelReasoning";
import { snapshotTurnModelControls } from "./turnControls";
import { DEFAULT_MODEL_PARAMETER_VALUES } from "@/const/modelParameterSettings";
import type { ModelParameterValue } from "@/types/modelParameterSettings";
import { subscribeRejectedSelection } from "./rejectedSelection";

interface ModelState {
  enabled: boolean;
  effort: ReasoningEffort;
  budget: number;
}
interface SessionState {
  modelId: string;
  values: Record<string, ModelState>;
}

export function useConversationModelControls(
  models: readonly ModelOption[],
  sessionKey: string,
  defaultModelId?: string,
  controlledModelId?: string
) {
  const [sessions, setSessions] = useState<Record<string, SessionState>>({});
  const [sampling, setSampling] = useState<Record<string, ModelParameterValue>>(
    {}
  );
  const [rejected, setRejected] = useState<Record<string, boolean>>({});
  const saved = sessions[sessionKey];
  const selectedId =
    controlledModelId ??
    saved?.modelId ??
    (models.some((m) => m.id === defaultModelId)
      ? defaultModelId
      : models[0]?.id);
  const model = models.find((m) => m.id === selectedId);
  const remembered = selectedId ? saved?.values[selectedId] : undefined;
  const options = Array.isArray(model?.efforts) ? model.efforts : [];
  const fallbackEffort = isReasoningEffort(model?.defaultEffort)
    ? model.defaultEffort
    : "auto";
  const effort =
    remembered?.effort === "auto" ||
    options.some((e) => e.id === remembered?.effort)
      ? (remembered?.effort ?? fallbackEffort)
      : fallbackEffort;
  const supported = Boolean(
    model?.efforts ||
    model?.budgetTokens ||
    model?.reasoningCapability?.status === "supported"
  );
  const enabled =
    supported && (remembered?.enabled ?? model?.defaultDeepThinking ?? false);
  const range = model?.budgetTokens;
  const rawBudget = remembered?.budget ?? model?.defaultBudgetTokens ?? 0;
  const budget =
    rawBudget > 0 && range
      ? Math.min(range.max, Math.max(range.min, rawBudget))
      : 0;
  const activeModelId = model?.id;
  const hasBudgetControl = Boolean(range);
  const value: ModelState = { enabled, effort, budget };
  const parameterScope = JSON.stringify([sessionKey, selectedId]);
  const samplingValue =
    sampling[parameterScope] ?? DEFAULT_MODEL_PARAMETER_VALUES;
  useEffect(
    () =>
      subscribeRejectedSelection((id) => {
        if (String(id) === selectedId)
          setRejected((current) => ({ ...current, [parameterScope]: true }));
      }),
    [selectedId, parameterScope]
  );
  const snapshot = useMemo(
    () =>
      activeModelId
        ? snapshotTurnModelControls(activeModelId, {
            deep_thinking: enabled,
            thinking_effort: hasBudgetControl ? "auto" : effort,
            ...(hasBudgetControl ? { reasoning_budget_tokens: budget } : {}),
            ...samplingValue,
          })
        : undefined,
    [activeModelId, enabled, effort, hasBudgetControl, budget, samplingValue]
  );
  const update = (patch: Partial<ModelState>) => {
    if (!selectedId || !model) return;
    setSessions((current) => ({
      ...current,
      [sessionKey]: {
        modelId: selectedId,
        values: {
          ...current[sessionKey]?.values,
          [selectedId]: { ...value, ...patch },
        },
      },
    }));
  };
  return {
    models,
    selectedModelId: selectedId,
    onModelChange: (modelId: string) => {
      if (!models.some((m) => m.id === modelId)) return;
      setRejected((current) => ({
        ...current,
        [JSON.stringify([sessionKey, modelId])]: false,
      }));
      setSessions((current) => ({
        ...current,
        [sessionKey]: {
          modelId,
          values: {
            ...current[sessionKey]?.values,
            ...(selectedId && model ? { [selectedId]: value } : {}),
          },
        },
      }));
    },
    deepThinking: enabled,
    onDeepThinkingChange: (next: boolean) =>
      update({
        enabled: next,
        ...(next && !enabled
          ? { effort: fallbackEffort, budget: model?.defaultBudgetTokens ?? 0 }
          : {}),
      }),
    thinkingEffort: range ? ("auto" as const) : effort,
    onThinkingEffortChange: (next: ReasoningEffort) => update({ effort: next }),
    reasoningBudgetTokens: budget,
    onReasoningBudgetTokensChange: (next: number) => update({ budget: next }),
    canSend: Boolean(model) && !rejected[parameterScope],
    modelParameterSettings: {
      scopeKey: parameterScope,
      value: samplingValue,
      defaultValue: DEFAULT_MODEL_PARAMETER_VALUES,
      onChange: (next: ModelParameterValue) =>
        setSampling((current) => ({ ...current, [parameterScope]: next })),
    },
    snapshot,
  };
}

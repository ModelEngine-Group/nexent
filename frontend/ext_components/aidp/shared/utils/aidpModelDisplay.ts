// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { AidpModelItem } from "../types/management";

/** Resolve labels without changing the canonical identifier used in requests. */
export function aidpModelLabel(
  modelName: string | null | undefined,
  models: AidpModelItem[] = []
): string | undefined {
  return (
    models
      .find((model) => model.model_name === modelName)
      ?.display_name?.trim() ||
    modelName ||
    undefined
  );
}

export function aidpModelOptions(models: AidpModelItem[] = []) {
  return models
    .filter(
      (model) =>
        typeof model.model_name === "string" && model.model_name.length > 0
    )
    .map((model) => ({
      value: model.model_name,
      label: aidpModelLabel(model.model_name, [model]),
    }));
}

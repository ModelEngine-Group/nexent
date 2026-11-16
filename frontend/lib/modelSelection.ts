// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/** Legacy callers without probe metadata retain their existing defaults. */
export function automaticModelId(
  models: readonly { id: string; disabled?: boolean; connectStatus?: string }[]
): string | undefined {
  return models.find(
    (model) =>
      !model.disabled &&
      (model.connectStatus === undefined || model.connectStatus === "available")
  )?.id;
}

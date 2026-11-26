// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { STTModelConfig } from "@/types/modelConfig";

export function isDictationConfigured(config?: STTModelConfig): boolean {
  if (!config?.modelName) return false;
  return config.modelFactory === "volcengine"
    ? Boolean(config.modelAppid && config.accessToken)
    : Boolean(config.apiConfig?.apiKey);
}

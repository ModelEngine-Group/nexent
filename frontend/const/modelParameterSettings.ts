// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ModelParameterValue } from "@/types/modelParameterSettings";

/** UI levels only; backend/provider conversion belongs to a future adapter. */
export const DEFAULT_MODEL_PARAMETER_VALUES: ModelParameterValue = {
  temperatureLevel: 50,
  topPLevel: 90,
};

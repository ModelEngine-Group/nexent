// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/** Optional provider-scale overrides. Absence inherits the configured default. */
export interface ModelParameterValue {
  temperature?: number;
  top_p?: number;
}

export interface ModelParameterSettingsControl {
  scopeKey?: string;
  value: ModelParameterValue;
  defaultValue: ModelParameterValue;
  disabled?: boolean;
  onChange: (value: ModelParameterValue) => void;
}

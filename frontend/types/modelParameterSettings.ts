// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/** Frontend levels only. A future integration adapter owns provider conversion. */
export interface ModelParameterValue {
  temperatureLevel: number;
  topPLevel: number;
}

export interface ModelParameterSettingsControl {
  scopeKey?: string;
  value: ModelParameterValue;
  defaultValue: ModelParameterValue;
  disabled?: boolean;
  onChange: (value: ModelParameterValue) => void;
}

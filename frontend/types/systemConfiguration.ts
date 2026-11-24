// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

export type SystemConfigurationValue = number | boolean | string[];
export type SystemConfigurationKind = "integer" | "number" | "boolean" | "resource_refs";
export type SystemConfigurationGroup =
  "tenant" | "capacity" | "upload" | "runtime";

export interface SystemConfigurationItem {
  key: string;
  value: SystemConfigurationValue;
  default_value: SystemConfigurationValue;
  kind: SystemConfigurationKind;
  group: SystemConfigurationGroup;
  label_key: string;
  description_key: string;
  unit_key: string | null;
  effect_key: string;
  recommendation_available: boolean;
}

export interface SystemConfigurationListResponse {
  items: SystemConfigurationItem[];
  total: number;
}

export type SystemConfigurationChanges = Record<
  string,
  SystemConfigurationValue
>;

export interface SystemConfigurationSaveResponse {
  saved: true;
  items: SystemConfigurationItem[];
  notification: "published" | "degraded";
}

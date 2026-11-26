// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

export type DenylistScope = "global" | "tenant";
export type DenylistResourceType = "mcp" | "tool" | "skill";

export interface DenylistItem {
  key: string;
  name: string;
  resource_type: DenylistResourceType;
  source?: string | null;
  description?: string;
  service?: string | null;
  parent_key?: string | null;
  global_blocked?: boolean;
  missing?: boolean;
}

export interface DenylistState {
  items: DenylistItem[];
  selected: string[];
  revision: string;
}

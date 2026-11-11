// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
export interface OperationsAuthorization {
  scope: "all_tenants" | "current_tenant";
  tenant_id: string;
  permissions: Record<"dashboard" | "configuration", string[]>;
}
export interface ResourceInventoryItem {
  kind: string;
  id: number;
  name: string;
  tenant_id: string;
}
export interface ResourceInventory {
  items: ResourceInventoryItem[];
  total: number;
  page: number;
  page_size: number;
}

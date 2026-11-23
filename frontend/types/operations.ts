// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
export interface OperationsAuthorization {
  scope: "all_tenants" | "current_tenant";
  tenant_id: string;
  permissions: Record<"dashboard" | "configuration", string[]>;
}

export interface OperationsResource {
  kind: "agent" | "model" | "mcp" | "knowledge";
  id: number;
  name: string | null;
  tenant_id: string;
}

export interface OperationsResourcePage {
  items: OperationsResource[];
  total: number;
}

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

export interface MonitoringDateScope {
  tenantId: string | null;
  startDate: string;
  endDate: string;
}

export type MonitoringCoverage = "covered" | "partial" | "uncovered";

export interface MonitoringPublication {
  coverage_state: MonitoringCoverage;
  data_as_of: string | null;
  is_stale: boolean;
}

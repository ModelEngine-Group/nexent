// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
export const DEFAULT_MONITORING_DASHBOARD_ALLOWED_ROLES = ["SU"] as const;
const normalizeRole = (role: string | null | undefined) =>
  role?.trim().toUpperCase() ?? "";

export function canViewMonitoringDashboard(
  role: string | readonly string[] | null | undefined,
  _retiredMode: boolean,
  allowedRoles?: readonly string[] | null
): boolean {
  const values = Array.isArray(role) ? role : [role];
  const allowed = (
    allowedRoles ?? DEFAULT_MONITORING_DASHBOARD_ALLOWED_ROLES
  ).map(normalizeRole);
  return values.some((value) => {
    const normalized = normalizeRole(value);
    return (
      !!normalized && normalized !== "SPEED" && allowed.includes(normalized)
    );
  });
}

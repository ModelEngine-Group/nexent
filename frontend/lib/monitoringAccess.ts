export const DEFAULT_MONITORING_DASHBOARD_ALLOWED_ROLES = [
  "SU",
  "SPEED",
] as const;

const normalizeRole = (role: string | null | undefined): string =>
  role?.trim().toUpperCase() ?? "";

export function canViewMonitoringDashboard(
  role: string | null | undefined,
  isSpeedMode: boolean,
  allowedRoles?: readonly string[] | null
): boolean {
  const effectiveRole = isSpeedMode ? "SPEED" : normalizeRole(role);
  if (!effectiveRole) return false;

  const configuredRoles =
    allowedRoles ?? DEFAULT_MONITORING_DASHBOARD_ALLOWED_ROLES;
  return configuredRoles.some(
    (configuredRole) => normalizeRole(configuredRole) === effectiveRole
  );
}

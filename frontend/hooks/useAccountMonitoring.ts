"use client";

import { useQuery } from "@tanstack/react-query";

import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { canViewMonitoringDashboard } from "@/lib/monitoringAccess";
import { monitoringService } from "@/services/monitoringService";

export function useAccountMonitoring() {
  const { user } = useAuthorizationContext();
  const { isSpeedMode } = useDeployment();
  const enabled = isSpeedMode || !!user;
  const { data: status } = useQuery({
    queryKey: ["account-monitoring-status", user?.id, user?.role, isSpeedMode],
    queryFn: monitoringService.fetchStatus,
    enabled,
    retry: false,
  });

  return enabled &&
    status?.telemetry_enabled &&
    canViewMonitoringDashboard(
      user?.role,
      isSpeedMode,
      status.dashboard_allowed_roles
    )
    ? status.dashboard_url || null
    : null;
}

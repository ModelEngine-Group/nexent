// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getMcpMonitoringCatalog } from "@/services/mcpMonitoringService";
import type { McpServiceFilter } from "@/types/mcpMonitoring";
import { listGroups } from "@/services/groupService";
import {
  checkOperationsScope,
  listOperationsMcpTools,
  listOperationsResources,
} from "@/services/operationsService";
import { fetchSkillsList } from "@/services/skillService";
import { getTenant, listTenants, type Tenant } from "@/services/tenantService";
import type { MonitoringTab } from "./monitoringFilters";

export function resourceKey(tenantId: string, id: number | string): string {
  return JSON.stringify([tenantId, id]);
}

export function mcpServiceKey(service: McpServiceFilter): string {
  return String(service.service_id ?? service.type);
}

export function useMonitoringDirectories({
  userId,
  userTenant,
  selectedTenant,
  canChooseTenant,
  canReadInventory,
  tab,
  selectedService,
  drilledMcpService,
}: {
  userId: string;
  userTenant: string;
  selectedTenant: string;
  canChooseTenant: boolean;
  canReadInventory: boolean;
  tab: MonitoringTab;
  selectedService?: string;
  drilledMcpService?: { tenantId: string; service: McpServiceFilter };
}) {
  const queryClient = useQueryClient();
  const queryKey = ["opsMonitoringDirectories", userId, userTenant] as const;
  const requestedTenant = canChooseTenant ? selectedTenant : userTenant;
  const scope = useQuery({
    queryKey: [...queryKey, "scope", requestedTenant],
    queryFn: () =>
      checkOperationsScope("dashboard", requestedTenant || undefined),
  });
  const tenant = scope.isSuccess ? scope.data.tenant_id : undefined;
  const tenants = useQuery({
    queryKey: [...queryKey, "tenants", canChooseTenant],
    enabled: canChooseTenant || Boolean(userTenant),
    queryFn: async () => {
      if (!canChooseTenant) return [await getTenant(userTenant)];
      const pageSize = 100;
      const choices: Tenant[] = [];
      let end = 1;
      for (let page = 1; page <= end; page += 1) {
        const result = await listTenants({ page, page_size: pageSize });
        choices.push(...result.data);
        if (page === 1) end = result.total_pages;
      }
      return choices;
    },
  });
  const groups = useQuery({
    queryKey: [...queryKey, "groups", tenant],
    enabled: tab !== "overview" && Boolean(tenant),
    queryFn: () => listGroups(tenant!),
  });
  const inventory = useQuery({
    queryKey: [...queryKey, "inventory", tenant],
    enabled:
      tenant !== undefined &&
      canReadInventory &&
      tab !== "skill" &&
      (tab !== "mcp" || tenant === null),
    queryFn: ({ signal }) => listOperationsResources(tenant ?? null, signal),
  });
  const skills = useQuery({
    queryKey: [...queryKey, "skills", tenant],
    enabled: tab === "skill" && Boolean(tenant),
    queryFn: () => fetchSkillsList(tenant, "mount"),
  });

  const mcpCatalog = useQuery({
    queryKey: [...queryKey, "mcpCatalog", { tenant }],
    enabled: (tab === "mcp" || tab === "overview") && tenant !== undefined,
    queryFn: ({ signal }) => getMcpMonitoringCatalog(tenant ?? null, signal),
  });
  // MCP catalog IDs are global; inventory supplies tenant labels for a platform scope.
  const mcpServiceTenant = (service: McpServiceFilter) =>
    tenant ??
    inventory.data?.find(
      (item) => item.kind === "mcp" && item.id === service.service_id
    )?.tenant_id;
  const catalogService =
    tab === "mcp"
      ? mcpCatalog.data?.find((item) => mcpServiceKey(item) === selectedService)
      : undefined;
  const historicalService =
    tab === "mcp" &&
    drilledMcpService &&
    drilledMcpService.tenantId === tenant &&
    mcpServiceKey(drilledMcpService.service) === selectedService
      ? drilledMcpService.service
      : undefined;
  const service = catalogService ?? historicalService;
  const serviceId = catalogService?.service_id;
  // The tool directory requires a registered service in the session tenant.
  const canReadTools =
    catalogService !== undefined &&
    catalogService.service_id !== null &&
    Boolean(userTenant) &&
    mcpServiceTenant(catalogService) === userTenant;
  const tools = useQuery({
    queryKey: [...queryKey, "tools", serviceId],
    enabled: canReadTools,
    queryFn: ({ signal }) => listOperationsMcpTools(serviceId!, signal),
  });

  const fetching =
    scope.isFetching ||
    tenants.isFetching ||
    (tab !== "overview" && groups.isFetching) ||
    (tab === "skill" ? skills.isFetching : inventory.isFetching) ||
    mcpCatalog.isFetching ||
    (canReadTools && tools.isFetching);

  return {
    tenant,
    scope,
    tenants,
    groups,
    inventory,
    skills,
    mcpCatalog,
    mcpServiceCount:
      tenant === undefined || mcpCatalog.isError
        ? undefined
        : mcpCatalog.data?.filter(({ type }) => type !== "builtin").length,
    mcpService: service,
    mcpServiceTenant,
    tools,
    canReadTools,
    fetching,
    refresh: () => queryClient.refetchQueries({ queryKey, type: "active" }),
  };
}

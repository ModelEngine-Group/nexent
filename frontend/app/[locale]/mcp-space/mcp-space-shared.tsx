import type {
  CommunityMcpCard,
  McpContainerConfigPayload,
  McpServiceItem,
} from "@/types/mcpTools";
import type { MineMcpCardItem } from "./components/MineMcpServiceCard";
import { FILTER_ALL, McpDeploymentType } from "@/const/mcpTools";
import {
  getDeploymentTypeLabelKey,
  resolveDeploymentType,
} from "@/lib/mcpTools";

export type DeploymentFilter = McpDeploymentType | typeof FILTER_ALL;

type DeploymentCountable = {
  transportType: CommunityMcpCard["transportType"];
  deploymentType?: McpDeploymentType;
  configJson?: Record<string, unknown>;
  serverUrl?: string;
};

const deploymentCategories = [
  McpDeploymentType.REMOTE_LINK,
  McpDeploymentType.CONTAINER,
  McpDeploymentType.API,
  McpDeploymentType.LOCAL_IMAGE,
];

export function getDeploymentCategoryStats(
  items: DeploymentCountable[],
  t: (key: string) => string
): Array<{ value: DeploymentFilter; label: string; count: number }> {
  const hasLocalImage = items.some(
    (item) => resolveDeploymentType(item) === McpDeploymentType.LOCAL_IMAGE
  );
  return [
    {
      value: FILTER_ALL,
      label: t("mcpTools.deploymentType.all"),
      count: items.length,
    },
    ...deploymentCategories
      .filter((dt) => dt !== McpDeploymentType.LOCAL_IMAGE || hasLocalImage)
      .map((deploymentType) => ({
        value: deploymentType,
        label: t(getDeploymentTypeLabelKey(deploymentType)),
        count: items.filter(
          (item) => resolveDeploymentType(item) === deploymentType
        ).length,
      })),
  ];
}

export function getDeduplicatedMineItems(
  localServices: McpServiceItem[],
  publishedServices: CommunityMcpCard[]
): MineMcpCardItem[] {
  // Only show local MCPs that belong to the current user or are shared via groups
  const myLocalServices = localServices.filter(
    (s) => s.permission === "EDIT" || s.groupIds
  );
  const linkedCommunityIds = new Set<number>();
  const localNames = new Set<string>();

  for (const service of myLocalServices) {
    if (service.communityId) linkedCommunityIds.add(service.communityId);
    localNames.add(normalizeMcpName(service.name));
  }

  const visiblePublishedServices = publishedServices.filter((service) => {
    // Published-by-me items (have sourceMcpId) are hidden from "我的" tab.
    // They are managed via the repository tab. This prevents them from
    // reappearing after the local copy is deleted.
    if (service.sourceMcpId != null) return false;
    if (service.communityId && linkedCommunityIds.has(service.communityId)) {
      return false;
    }
    return !localNames.has(normalizeMcpName(service.name));
  });

  return [
    ...myLocalServices.map((service) => ({
      kind: "local" as const,
      service,
    })),
    ...visiblePublishedServices.map((service) => ({
      kind: "community" as const,
      service,
    })),
  ];
}

function normalizeMcpName(name: string): string {
  return name.trim().toLowerCase();
}

export function getMineItemKey(item: MineMcpCardItem): string {
  return item.kind === "local"
    ? `local-${item.service.mcpId}`
    : `community-${item.service.communityId || item.service.name}`;
}

export function toMcpContainerConfigPayload(
  value?: Record<string, unknown>
): McpContainerConfigPayload | undefined {
  if (!value || typeof value.mcpServers !== "object" || !value.mcpServers) {
    return undefined;
  }
  return value as unknown as McpContainerConfigPayload;
}

export function resolveOnlineService(
  service: McpServiceItem,
  serviceByCommunityId: Map<number, CommunityMcpCard>,
  serviceBySourceMcpId: Map<number, CommunityMcpCard>
): CommunityMcpCard | undefined {
  const reviewService = serviceBySourceMcpId.get(service.mcpId);
  if (reviewService) return reviewService;
  if (service.communityId) {
    const marketService = serviceByCommunityId.get(service.communityId);
    if (
      marketService?.sourceMcpId == null ||
      marketService.sourceMcpId === service.mcpId
    ) {
      return marketService;
    }
  }
  return undefined;
}

export function ResponsiveCardGrid({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="grid items-stretch gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {children}
    </div>
  );
}

export function PlaceholderBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-center rounded-xl border border-dashed border-slate-200 px-6 py-16 text-center text-slate-500 dark:border-slate-700">
      {children}
    </div>
  );
}

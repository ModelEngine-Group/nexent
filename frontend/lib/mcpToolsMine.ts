import type { CommunityMcpCard, McpServiceItem } from "@/types/mcpTools";

// ---------------------------------------------------------------------------
// Review status helpers
// ---------------------------------------------------------------------------

export function isCancelableReviewStatus(
  status?: string | null
): boolean {
  return status === "pending" || status === "rejected";
}

export function isTakeDownableReviewStatus(
  status?: string | null
): boolean {
  return status === "approved";
}

// ---------------------------------------------------------------------------
// Date formatting
// ---------------------------------------------------------------------------

export function formatMineDate(iso?: string | null): string | null {
  if (!iso) return null;
  const timestamp = Date.parse(iso);
  if (Number.isNaN(timestamp)) return null;
  return new Date(timestamp).toISOString().slice(0, 10);
}

// ---------------------------------------------------------------------------
// Determine which dropdown menu actions to show on a Mine tab card
// ---------------------------------------------------------------------------

export type MineCardMenuAction =
  | "apply-for-listing"
  | "view-review-progress"
  | "submit-version-update"
  | "unpublish-online-version"
  | "refresh-tool-count"
  | "delete";

export function getMineCardMenuActions(
  item: { kind: "local"; service: McpServiceItem } | { kind: "community"; service: CommunityMcpCard },
  onlineService?: CommunityMcpCard
): MineCardMenuAction[] {
  const actions: MineCardMenuAction[] = [];
  const isLocal = item.kind === "local";
  const localService = isLocal ? item.service : null;
  const isOwned = item.kind === "community" || (
    localService?.permission === "EDIT" && localService?.source === "local"
  );

  if (!isOwned) {
    return ["delete"];
  }

  const reviewStatus = onlineService?.reviewStatus || item.service.reviewStatus;

  if (reviewStatus === "pending") {
    actions.push("view-review-progress");
  } else if (reviewStatus === "approved") {
    actions.push("submit-version-update");
  } else {
    // never submitted, rejected, or offline → apply for listing
    actions.push("apply-for-listing");
  }

  const isInRepository = isLocal
    ? Boolean(localService?.isListedInRepository)
    : reviewStatus === "approved";

  if (isInRepository) {
    actions.push("unpublish-online-version");
  }

  if (item.kind === "local") {
    actions.push("refresh-tool-count");
  }

  actions.push("delete");
  return actions;
}

// ---------------------------------------------------------------------------
// Review badge display config
// ---------------------------------------------------------------------------

export type MineCardReviewVariant = "pending" | "approved" | "rejected";

export interface MineCardReviewBadge {
  labelKey: string;
  variant: MineCardReviewVariant;
}

export function getMineCardReviewBadge(
  item: { kind: "local"; service: McpServiceItem } | { kind: "community"; service: CommunityMcpCard },
  onlineService?: CommunityMcpCard
): MineCardReviewBadge | null {
  const isLocal = item.kind === "local";
  const reviewStatus = onlineService?.reviewStatus || item.service.reviewStatus;

  if (!reviewStatus || reviewStatus === "offline") return null;

  switch (reviewStatus) {
    case "pending":
      return { labelKey: "mcpTools.mine.status.reviewing", variant: "pending" };
    case "approved":
      return { labelKey: "mcpTools.mine.status.listed", variant: "approved" };
    case "rejected":
      return { labelKey: "mcpTools.mine.status.rejected", variant: "rejected" };
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Online service resolver
// ---------------------------------------------------------------------------

export function resolveOnlineService(
  service: McpServiceItem,
  serviceByCommunityId: Map<number, CommunityMcpCard>,
  serviceBySourceMcpId: Map<number, CommunityMcpCard>
): CommunityMcpCard | undefined {
  const reviewService = serviceBySourceMcpId.get(service.mcpId);
  if (reviewService) return reviewService;
  if (service.communityId) {
    const marketService = serviceByCommunityId.get(service.communityId);
    if (marketService?.sourceMcpId == null || marketService.sourceMcpId === service.mcpId) {
      return marketService;
    }
  }
  return undefined;
}

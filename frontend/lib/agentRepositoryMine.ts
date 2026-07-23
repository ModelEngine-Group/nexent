import type {
  AgentRepositoryListingItem,
  MyAgentRepositoryInfoItem,
  MyEditableAgentItem,
} from "@/types/agentRepository";
import { isSingleSimpleEmoji } from "@/lib/agentRepositoryIcon";

export type MineCardMenuAction = "apply" | "review" | "reviewUpdate";

function parseCreateTime(value?: string | null): number {
  if (!value) {
    return 0;
  }
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

export function pickLatestRepositoryInfo(
  items: MyAgentRepositoryInfoItem[]
): MyAgentRepositoryInfoItem | null {
  if (!items.length) {
    return null;
  }
  return [...items].sort(
    (a, b) => parseCreateTime(b.create_time) - parseCreateTime(a.create_time)
  )[0];
}

export function pickLatestSharedVersionName(
  items: MyAgentRepositoryInfoItem[]
): string | null {
  const sharedItems = items.filter((item) => item.status === "shared");
  const latest = pickLatestRepositoryInfo(sharedItems);
  const versionName = latest?.version_label?.trim();
  return versionName || null;
}

export function formatMineDate(iso?: string | null): string | null {
  if (!iso) {
    return null;
  }
  const timestamp = Date.parse(iso);
  if (Number.isNaN(timestamp)) {
    return null;
  }
  return new Date(timestamp).toISOString().slice(0, 10);
}

export function isCurrentVersionListed(agent: MyEditableAgentItem): boolean {
  const currentVersionNo = agent.current_version_no ?? 0;
  if (currentVersionNo <= 0) {
    return false;
  }
  return (agent.repository_info ?? []).some(
    (item) => item.version_no === currentVersionNo
  );
}

export function pickReviewDisplayRepositoryInfo(
  items: MyAgentRepositoryInfoItem[]
): MyAgentRepositoryInfoItem | null {
  const pendingItems = items.filter((item) => item.status === "pending_review");
  const pending = pickLatestRepositoryInfo(pendingItems);
  if (pending) {
    return pending;
  }
  const rejectedItems = items.filter((item) => item.status === "rejected");
  const rejected = pickLatestRepositoryInfo(rejectedItems);
  if (rejected) {
    return rejected;
  }
  const sharedItems = items.filter((item) => item.status === "shared");
  return pickLatestRepositoryInfo(sharedItems);
}

export function findRepositoryInfoById(
  items: MyAgentRepositoryInfoItem[],
  agentRepositoryId: number
): MyAgentRepositoryInfoItem | null {
  return (
    items.find((item) => item.agent_repository_id === agentRepositoryId) ?? null
  );
}

export function resolveReviewModalMode(
  agent: MyEditableAgentItem,
  repositoryInfo: MyAgentRepositoryInfoItem
): "review" | "reviewUpdate" {
  const repositoryInfoList = agent.repository_info ?? [];
  const hasShared = repositoryInfoList.some((item) => item.status === "shared");
  const isPendingOrRejected =
    repositoryInfo.status === "pending_review" ||
    repositoryInfo.status === "rejected";
  if (isPendingOrRejected && hasShared) {
    return "reviewUpdate";
  }
  return "review";
}

export function pickPendingReviewRepositoryInfo(
  items: MyAgentRepositoryInfoItem[]
): MyAgentRepositoryInfoItem | null {
  const pendingItems = items.filter((item) => item.status === "pending_review");
  return pickLatestRepositoryInfo(pendingItems);
}

export function isCancelableRepositoryStatus(
  status: MyAgentRepositoryInfoItem["status"]
): boolean {
  return status === "pending_review" || status === "rejected";
}

export function isTakeDownableRepositoryStatus(
  status: MyAgentRepositoryInfoItem["status"]
): boolean {
  return status === "shared";
}

export function getMineCardMenuActions(
  agent: MyEditableAgentItem
): MineCardMenuAction[] {
  const repositoryInfo = agent.repository_info ?? [];
  const actions: MineCardMenuAction[] = [];
  const currentVersionNo = agent.current_version_no ?? 0;
  const canEdit = agent.permission !== "READ_ONLY";

  if (canEdit && currentVersionNo > 0 && !isCurrentVersionListed(agent)) {
    actions.push("apply");
  }

  if (repositoryInfo.length > 0) {
    const hasPending = repositoryInfo.some(
      (item) => item.status === "pending_review"
    );
    const hasShared = repositoryInfo.some((item) => item.status === "shared");
    const hasRejected = repositoryInfo.some((item) => item.status === "rejected");
    if ((hasPending || hasRejected) && hasShared) {
      actions.push("reviewUpdate");
    } else {
      actions.push("review");
    }
  }

  return actions;
}

export function formatRepositoryVersionLabel(
  item: MyAgentRepositoryInfoItem
): string {
  const label = item.version_label?.trim();
  if (label) {
    return label;
  }
  if (item.version_no != null) {
    return `v${item.version_no}`;
  }
  return "";
}

export type MineCardRepositoryStatusVariant = "pending" | "shared" | "rejected";

export interface MineCardRepositoryStatusBadge {
  labelKey: string;
  versionLabel: string;
  variant: MineCardRepositoryStatusVariant;
}

const MINE_STATUS_LABEL_KEYS = {
  reviewing: "agentRepository.mine.status.reviewing",
  updateReviewing: "agentRepository.mine.status.updateReviewing",
  listed: "agentRepository.mine.status.listed",
  rejected: "agentRepository.mine.status.rejected",
} as const;

export function getMineCardRepositoryStatusBadge(
  items: MyAgentRepositoryInfoItem[]
): MineCardRepositoryStatusBadge | null {
  const displayItem = pickReviewDisplayRepositoryInfo(items);
  if (!displayItem) {
    return null;
  }

  const versionLabel = formatRepositoryVersionLabel(displayItem);
  const hasShared = items.some((item) => item.status === "shared");

  switch (displayItem.status) {
    case "pending_review":
      return {
        labelKey: hasShared
          ? MINE_STATUS_LABEL_KEYS.updateReviewing
          : MINE_STATUS_LABEL_KEYS.reviewing,
        versionLabel,
        variant: "pending",
      };
    case "rejected":
      return {
        labelKey: MINE_STATUS_LABEL_KEYS.rejected,
        versionLabel,
        variant: "rejected",
      };
    case "shared":
      return {
        labelKey: MINE_STATUS_LABEL_KEYS.listed,
        versionLabel,
        variant: "shared",
      };
    default:
      return null;
  }
}

export function pickApplyListingPrefillSource(
  items: AgentRepositoryListingItem[],
  currentVersionLabel?: string | null
): AgentRepositoryListingItem | null {
  const normalizedVersion = currentVersionLabel?.trim();
  if (normalizedVersion) {
    const byVersion = items.find(
      (item) => item.version_label?.trim() === normalizedVersion
    );
    if (byVersion) {
      return byVersion;
    }
  }

  const shared = items.find((item) => item.status === "shared");
  return shared ?? null;
}

export interface ApplyListingFormPrefill {
  icon: string | null;
  tags: string[];
}

function normalizeApplyListingTags(tags: string[], maxTags: number): string[] {
  const normalized: string[] = [];
  const seen = new Set<string>();
  for (const rawTag of tags) {
    const tag = rawTag.trim();
    if (!tag || seen.has(tag)) {
      continue;
    }
    seen.add(tag);
    normalized.push(tag);
    if (normalized.length >= maxTags) {
      break;
    }
  }
  return normalized;
}

export function buildApplyListingFormPrefill(
  item: AgentRepositoryListingItem | null,
  options: {
    maxTags?: number;
  } = {}
): ApplyListingFormPrefill | null {
  if (!item) {
    return null;
  }

  const maxTags = options.maxTags ?? 5;
  const trimmedIcon = item.icon?.trim();

  const icon =
    trimmedIcon && isSingleSimpleEmoji(trimmedIcon) ? trimmedIcon : null;

  const tags = normalizeApplyListingTags(item.tags ?? [], maxTags);

  return {
    icon,
    tags,
  };
}

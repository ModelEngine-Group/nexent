import type {
  MyAgentRepositoryInfoItem,
  MyEditableAgentItem,
} from "@/types/agentRepository";

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

export function getMineCardMenuActions(
  agent: MyEditableAgentItem
): MineCardMenuAction[] {
  const repositoryInfo = agent.repository_info ?? [];
  const actions: MineCardMenuAction[] = [];
  const currentVersionNo = agent.current_version_no ?? 0;

  if (currentVersionNo > 0 && !isCurrentVersionListed(agent)) {
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

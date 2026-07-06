import type {
  MySkillRepositoryInfoItem,
  SkillRepositoryListingStatus,
} from "@/types/skillRepository";

export const STATUS_LABELS: Record<SkillRepositoryListingStatus, string> = {
  not_shared: "未上架",
  pending_review: "待审核",
  rejected: "已驳回",
  shared: "已上架",
};

export const STATUS_COLORS: Record<SkillRepositoryListingStatus, string> = {
  not_shared: "default",
  pending_review: "processing",
  rejected: "error",
  shared: "success",
};

export function parseRepositoryTime(value?: string | null): number {
  if (!value) return 0;
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

export function formatRepositoryDate(value?: string | null): string | null {
  const timestamp = parseRepositoryTime(value);
  if (!timestamp) return null;
  return new Date(timestamp).toISOString().slice(0, 10);
}

export function getSkillSourceLabel(source?: string | null): string {
  if (source === "custom") {
    return "自定义";
  }
  if (source === "repository") {
    return "仓库";
  }
  return source || "-";
}

export function pickLatestRepositoryInfo(
  items: MySkillRepositoryInfoItem[]
): MySkillRepositoryInfoItem | null {
  if (!items.length) return null;
  return [...items].sort(
    (a, b) => parseRepositoryTime(b.create_time) - parseRepositoryTime(a.create_time)
  )[0];
}

export function pickReviewDisplayRepositoryInfo(
  items: MySkillRepositoryInfoItem[]
): MySkillRepositoryInfoItem | null {
  const pending = pickLatestRepositoryInfo(
    items.filter((item) => item.status === "pending_review")
  );
  if (pending) return pending;

  const rejected = pickLatestRepositoryInfo(
    items.filter((item) => item.status === "rejected")
  );
  if (rejected) return rejected;

  return pickLatestRepositoryInfo(
    items.filter((item) => item.status === "shared")
  );
}

export function isCancelableRepositoryStatus(
  status: MySkillRepositoryInfoItem["status"]
): boolean {
  return status === "pending_review" || status === "rejected";
}

export function isTakeDownableRepositoryStatus(
  status: MySkillRepositoryInfoItem["status"]
): boolean {
  return status === "shared";
}

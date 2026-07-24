import type {
  MySkillRepositoryInfoItem,
  SkillRepositoryListingStatus,
} from "@/types/skillRepository";

type Translate = (key: string, options?: Record<string, unknown>) => string;

export const STATUS_LABEL_KEYS: Record<SkillRepositoryListingStatus, string> = {
  not_shared: "skillRepository.status.notShared",
  pending_review: "skillRepository.status.pendingReview",
  rejected: "skillRepository.status.rejected",
  shared: "skillRepository.status.shared",
};

export const STATUS_COLORS: Record<SkillRepositoryListingStatus, string> = {
  not_shared: "default",
  pending_review: "processing",
  rejected: "error",
  shared: "success",
};

export function getSkillRepositoryStatusLabel(
  t: Translate,
  status: SkillRepositoryListingStatus
): string {
  return t(STATUS_LABEL_KEYS[status]);
}

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

export function getSkillSourceLabel(
  source: string | null | undefined,
  t: Translate
): string {
  if (source === "custom") {
    return t("skillRepository.source.custom");
  }
  if (source === "repository") {
    return t("skillRepository.source.repository");
  }
  return source || "-";
}

export function pickLatestRepositoryInfo(
  items: MySkillRepositoryInfoItem[]
): MySkillRepositoryInfoItem | null {
  if (!items.length) return null;
  return [...items].sort(
    (a, b) =>
      parseRepositoryTime(b.create_time) - parseRepositoryTime(a.create_time)
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

  const shared = pickLatestRepositoryInfo(
    items.filter((item) => item.status === "shared")
  );
  if (shared) return shared;

  return rejected;
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

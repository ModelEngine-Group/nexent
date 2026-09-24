import type {
  SkillRepositoryListingDetail,
  SkillRepositoryListingStatus,
} from "@/types/skillRepository";

export interface SkillRepositoryDetailView {
  title: string;
  description: string;
  author: string | null;
  status: SkillRepositoryListingStatus;
  tags: string[];
  downloads: number;
  updatedAt: string;
}

function formatDate(value?: string | null): string | null {
  if (!value) return null;
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp)
    ? null
    : new Date(timestamp).toISOString().slice(0, 10);
}

export function mapSkillRepositoryDetail(
  detail: SkillRepositoryListingDetail
): SkillRepositoryDetailView {
  return {
    title: detail.name.trim(),
    description: detail.description?.trim() || "",
    author: detail.author?.trim() || null,
    status: detail.status,
    tags: (detail.tags ?? []).map((tag) => tag.trim()).filter(Boolean),
    downloads: detail.downloads ?? 0,
    updatedAt:
      formatDate(detail.updated_at) || formatDate(detail.created_at) || "-",
  };
}

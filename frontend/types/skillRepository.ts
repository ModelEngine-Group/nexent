/**
 * Types for tenant skill repository marketplace listings.
 */

export type SkillRepositoryListingStatus =
  "not_shared" | "pending_review" | "rejected" | "shared";

export type MineOwnershipFilter = "all" | "created" | "others";

export interface SkillRepositoryListingItem {
  skill_repository_id: number;
  skill_id?: number;
  name: string;
  description?: string | null;
  source?: string | null;
  status: SkillRepositoryListingStatus;
  icon?: string | null;
  tags?: string[];
  downloads?: number;
  category_id?: number | null;
  author?: string | null;
  submitted_by?: string | null;
}

export interface SkillRepositoryListingPagination {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface SkillRepositoryListingListResponse {
  items: SkillRepositoryListingItem[];
  pagination?: SkillRepositoryListingPagination;
}

export interface SkillRepositoryListingListParams {
  status?: SkillRepositoryListingStatus;
  skill_id?: number;
  category_id?: number;
  page?: number;
  page_size?: number;
  search?: string;
  sort_by_update_time?: boolean;
}

export interface SkillRepositoryListingDetail extends SkillRepositoryListingItem {
  skill_info_json?: Record<string, unknown>;
  skill_zip_base64?: string;
  created_at?: string | null;
  updated_at?: string | null;
  is_updated?: boolean;
}

export interface MySkillRepositoryInfoItem {
  skill_repository_id: number;
  status: Extract<
    SkillRepositoryListingStatus,
    "shared" | "pending_review" | "rejected"
  >;
  create_time?: string | null;
}

export interface MyEditableSkillItem {
  skill_id: number;
  name?: string | null;
  description?: string | null;
  source?: string | null;
  tags?: string[];
  group_ids?: number[];
  ingroup_permission?: "EDIT" | "READ_ONLY" | "PRIVATE" | null;
  created_by?: string | null;
  updated_by?: string | null;
  create_time?: string | null;
  update_time?: string | null;
  updated_at?: string | null;
  downloads?: number;
  permission?: "EDIT" | "READ_ONLY" | "PRIVATE";
  can_publish?: boolean;
  repository_info: MySkillRepositoryInfoItem[];
}

export interface NewSkillPaddingItem {
  new_skill_padding: true;
}

export type MyEditableSkillListItem = MyEditableSkillItem | NewSkillPaddingItem;

export interface MyEditableSkillOwnershipCounts {
  all: number;
  created: number;
  others: number;
}

export interface MyEditableSkillListParams {
  ownership?: MineOwnershipFilter;
  page?: number;
  page_size?: number;
  search?: string;
  new_skill_padding?: boolean;
}

export interface MyEditableSkillPagination {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface MyEditableSkillListResponse {
  items: MyEditableSkillListItem[];
  counts: MyEditableSkillOwnershipCounts;
  pagination: MyEditableSkillPagination;
}

export interface SkillRepositoryListingCreatePayload {
  icon?: string;
  category_id?: number | null;
  tags?: string[];
}

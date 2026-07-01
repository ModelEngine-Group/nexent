/**
 * Types for tenant agent repository (marketplace listings)
 */

export type AgentRepositoryListingStatus =
  | "not_shared"
  | "pending_review"
  | "rejected"
  | "shared";

export interface AgentRepositoryListingItem {
  agent_repository_id: number;
  agent_id?: number;
  name: string;
  display_name?: string | null;
  description?: string | null;
  author?: string | null;
  status: AgentRepositoryListingStatus;
  icon?: string | null;
  tags?: string[];
  tool_count?: number | null;
  version_label?: string | null;
  downloads?: number;
  category_id?: number | null;
  submitted_by?: string | null;
}

export interface AgentRepositoryListingPagination {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface AgentRepositoryListingListResponse {
  items: AgentRepositoryListingItem[];
  pagination?: AgentRepositoryListingPagination;
}

export interface AgentRepositoryListingListParams {
  status?: AgentRepositoryListingStatus;
  agent_id?: number;
  category_id?: number;
  page?: number;
  page_size?: number;
  search?: string;
}

export interface AgentRepositoryCategoryItem {
  id: number;
  key: string;
  /** Legacy fallback when resolving labels from old API payloads. */
  name?: string;
}

export interface AgentRepositoryListingDetail {
  agent_repository_id: number;
  agent_id?: number | null;
  name: string;
  display_name?: string | null;
  description?: string | null;
  author?: string | null;
  icon?: string | null;
  status: AgentRepositoryListingStatus;
  version_label?: string | null;
  downloads?: number;
  created_at?: string | null;
  model_name?: string | null;
  duty_prompt?: string | null;
  tools?: string[];
}

export interface MyAgentRepositoryInfoItem {
  agent_repository_id: number;
  status: Extract<
    AgentRepositoryListingStatus,
    "shared" | "pending_review" | "rejected"
  >;
  version_no?: number | null;
  version_label?: string | null;
  create_time?: string | null;
}

export interface MyEditableAgentItem {
  agent_id: number;
  name?: string | null;
  description?: string | null;
  current_version_no?: number | null;
  version_label?: string | null;
  version_create_time?: string | null;
  /** EDIT: editable, READ_ONLY: read-only (from /agent/list permission logic). */
  permission?: "EDIT" | "READ_ONLY";
  /** Total downloads summed across all repository listings for this agent_id. */
  downloads?: number;
  repository_info: MyAgentRepositoryInfoItem[];
}

export interface MyEditableAgentPaddingItem {
  new_agent_padding: true;
}

export type MyEditableAgentListItem =
  | MyEditableAgentItem
  | MyEditableAgentPaddingItem;

export function isNewAgentPaddingItem(
  item: MyEditableAgentListItem
): item is MyEditableAgentPaddingItem {
  return "new_agent_padding" in item && item.new_agent_padding === true;
}

export type MineOwnershipFilter = "all" | "created" | "others";

export interface MyEditableAgentOwnershipCounts {
  all: number;
  created: number;
  others: number;
}

export interface MyEditableAgentListParams {
  ownership?: MineOwnershipFilter;
  page?: number;
  page_size?: number;
  search?: string;
  new_agent_padding?: boolean;
}

export interface MyEditableAgentPagination {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export interface MyEditableAgentListResponse {
  items: MyEditableAgentListItem[];
  counts: MyEditableAgentOwnershipCounts;
  pagination: MyEditableAgentPagination;
}

export interface AgentRepositoryListingCreatePayload {
  icon: string;
  category_id: number;
  tags: string[];
}

export type RepositoryImportRequirementType =
  | "model"
  | "knowledge_base"
  | "mcp"
  | "skill"
  | "tool";

export interface RepositoryImportRequirementItem {
  type: RepositoryImportRequirementType;
  key: string;
  name: string;
  description?: string | null;
  available: boolean;
  reason_code?: string | null;
}

export interface RepositoryImportPrecheckResponse {
  agent_repository_id: number;
  display_name: string;
  total_count: number;
  available_count: number;
  percent: number;
  has_abnormal: boolean;
  items: RepositoryImportRequirementItem[];
}

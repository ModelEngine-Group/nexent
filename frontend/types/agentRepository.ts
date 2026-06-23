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

export interface AgentRepositoryListingListResponse {
  items: AgentRepositoryListingItem[];
}

export interface AgentRepositoryListingListParams {
  status?: AgentRepositoryListingStatus;
  agent_id?: number;
  deduplicate_by_agent_id?: boolean;
  category_id?: number;
}

export interface AgentRepositoryCategoryItem {
  id: number;
  name: string;
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
  repository_info: MyAgentRepositoryInfoItem[];
}

export type MineOwnershipFilter = "all" | "created" | "others";

export interface MyEditableAgentOwnershipCounts {
  all: number;
  created: number;
  others: number;
}

export interface MyEditableAgentListParams {
  ownership?: MineOwnershipFilter;
}

export interface MyEditableAgentListResponse {
  items: MyEditableAgentItem[];
  counts: MyEditableAgentOwnershipCounts;
}

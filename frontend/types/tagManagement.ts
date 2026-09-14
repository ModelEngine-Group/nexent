/**
 * Typed contracts for the unified tag management APIs.
 *
 * Keep in sync with backend/consts/model.py tag models and the
 * /api/tag-libraries router in backend/apps/tag_management_app.py.
 */

export type TagStatus = "active" | "disabled";
export type TagSelectionMode = "single_select" | "multi_select" | "no_value";
export type TagBucketKey = "default_resource" | "knowledge_content";
export type TagResourceType =
  | "agent"
  | "skill"
  | "tool"
  | "mcp_service"
  | "knowledge_base"
  | "knowledge_document";
export type TagDocumentProvider = "local" | "aidp";
export type TagProjectionStatus =
  | "pending"
  | "synced"
  | "failed"
  | "unsupported"
  | "not_projected";
export type TagBulkOutcome =
  | "updated"
  | "not_found_or_forbidden"
  | "validation";

export interface TagAudit {
  created_by?: string | null;
  updated_by?: string | null;
  create_time?: string | null;
  update_time?: string | null;
}

export interface TagLibrary extends TagAudit {
  bucket_id: number;
  bucket_key: TagBucketKey;
  bucket_name: string;
  status: TagStatus;
  resource_types: TagResourceType[];
  definition_count: number;
  definition_capacity: number;
}

export interface TagValue extends TagAudit {
  value_id: number;
  display_value: string;
  normalized_value: string;
  sort_order: number;
  status: TagStatus;
}

export interface TagDefinition extends TagAudit {
  definition_id: number;
  bucket_id: number;
  definition_key: string;
  definition_name: string;
  selection_mode: TagSelectionMode;
  sort_order: number;
  status: TagStatus;
  active_value_count: number;
  value_capacity: number;
  values?: TagValue[] | null;
}

export interface TagDefinitionUsage {
  definition_id: number;
  active_value_count: number;
  active_usage_count: number;
  value_capacity: number;
}

export interface TagValueUsage {
  value_id: number;
  active_usage_count: number;
}

export interface TagDeleteResult {
  success: boolean;
}

export interface TagConflictDetails {
  definition_id?: number | null;
  value_id?: number | null;
  active_value_count?: number | null;
  active_usage_count?: number | null;
  resources_with_multiple_values?: number | null;
  limit?: number | null;
  current_count?: number | null;
  scope?: "definition" | "value" | "assignment" | null;
}

export interface TagConflict {
  message: string;
  details: TagConflictDetails;
}

export interface TagAssignmentValue {
  definition_id: number;
  definition_key: string;
  definition_name: string;
  selection_mode: TagSelectionMode;
  value_id: number;
  display_value: string;
  value_status: TagStatus;
}

export interface TagProjectionStatusInfo {
  status: TagProjectionStatus;
  version: number;
  tag_count: number;
  last_error?: string | null;
  retry_count: number;
  last_attempt_at?: string | null;
  next_attempt_at?: string | null;
  update_time?: string | null;
}

export interface TagAssignment {
  resource_type: TagResourceType;
  resource_id: string;
  assignment_count: number;
  assignment_capacity: number;
  assignments: TagAssignmentValue[];
  projection_status?: TagProjectionStatusInfo | null;
}

export interface TagLegacyFlatTagsProjection {
  resource_type: TagResourceType;
  resource_id: string;
  tags: string[];
  count: number;
  limit: number;
  deprecated: true;
}

export interface TagAssignmentBulkTarget {
  resource_id: string;
  provider?: string | null;
  knowledge_base_id?: string | null;
  value_ids: number[];
}

export interface TagAssignmentBulkOutcome {
  resource_id: string;
  outcome: TagBulkOutcome;
  assignment?: TagAssignment | null;
  message?: string | null;
  details?: TagConflictDetails | null;
}

export interface TagDocumentBatchStatusEntry {
  document_id: string;
  assignment_count: number;
  projection_status?: TagProjectionStatusInfo | null;
}

export interface TagDocumentPredicate {
  definition_id: number;
  value_ids: number[];
}

/**
 * Structured tag predicate for non-document resources. Same shape as a
 * document predicate (OR within a definition, AND across definitions), kept
 * under a resource-generic name so Agent/MCP/Knowledge Base list flows can use
 * it without the document-specific naming.
 */
export interface TagResourcePredicate {
  definition_id: number;
  value_ids: number[];
}

/**
 * Result of narrowing an already-authorized resource id set by tag predicates.
 */
export interface TagResourceFilterResult {
  resource_type: string;
  matched_resource_ids: string[];
}

// ---- Request payloads -------------------------------------------------------

export interface TagDefinitionCreatePayload {
  definition_key?: string;
  definition_name: string;
  selection_mode: TagSelectionMode;
  initial_values: string[];
  sort_order?: number;
}

export interface TagDefinitionUpdatePayload {
  definition_name?: string | null;
  selection_mode?: TagSelectionMode | null;
}

export interface TagValueCreatePayload {
  display_value: string;
  sort_order?: number;
}

export interface TagValueUpdatePayload {
  display_value: string;
}

export interface TagStatusUpdatePayload {
  status: TagStatus;
}

export interface TagOrderUpdatePayload {
  sort_order: number;
}

export interface TagAssignmentReplacePayload {
  value_ids: number[];
}

export interface TagAssignmentBulkReplacePayload {
  targets: TagAssignmentBulkTarget[];
}

// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/** Contracts for the AIDP ontology and Metadata management pages. */

export type AidpOntologyKind = "type" | "entity";

export interface AidpOntologyDomain {
  domain_id: string;
  name: string;
  description: string;
  /** Trusted count of knowledge bases bound to this domain; 0 is a real value. */
  bound_kb_count: number | null;
  /** Optional AIDP extensions; null/undefined means the list did not return it. */
  metadata_count?: number | null;
  entity_count?: number | null;
  rule_count?: number | null;
  created_by?: string | null;
  create_time?: string | number | null;
  update_time?: string | number | null;
}

export interface AidpOntologyDomainListResponse {
  value: AidpOntologyDomain[];
  total_count: number;
  has_more: boolean;
  total_reliable: boolean;
}

export interface AidpOntologyEntityProperty {
  api_name: string;
  display_name?: string;
  value?: string;
}

export interface AidpOntologyEntity {
  entity_id: string | null;
  api_name: string;
  display_name: string;
  description: string;
  kind: AidpOntologyKind | null;
  type_id?: string | null;
  properties: AidpOntologyEntityProperty[];
  primary_properties: string[];
  parent_entities: unknown[];
  synonym_entities: unknown[];
  child_entities?: unknown[];
  /** Optional AIDP audit values; absent fields render as an em dash. */
  create_time?: string | null;
  update_time?: string | null;
  /** Demo-only count; AIDP has no per-entity chunk count API. */
  chunk_count?: number | null;
  extended_properties?: Array<{ key: string; value: string }>;
  /** Count of knowledge bases bound to the owning ontology domain. */
  bound_kb_count: number | null;
}

export interface AidpOntologyEntityListResponse {
  value: AidpOntologyEntity[];
  total_count: number;
  has_more: boolean;
  total_reliable: boolean;
  bound_kb_count: number | null;
}

export interface AidpOntologyEntityCreatePayload {
  kind: AidpOntologyKind;
  api_name: string;
  display_name?: string;
  description?: string;
  properties?: AidpOntologyEntityProperty[];
  primary_properties?: string[];
  type_id?: string;
  /** AIDP create accepts up to 9 parent / synonym entity IDs. */
  parent_entities?: string[];
  synonym_entities?: string[];
  /** Children exist only as is-a Relations; applied after the entity exists. */
  child_entities?: string[];
}

export interface AidpOntologyEntityUpdatePayload {
  display_name?: string;
  description?: string;
  properties?: AidpOntologyEntityProperty[];
  primary_properties?: string[];
  /** Translated to Relations create/delete by the BFF. */
  parent_entities?: string[];
  child_entities?: string[];
  /** Stored in the `synonym` property by the BFF. */
  synonym_entities?: string[];
}

export interface AidpOntologyBinding {
  /** Present only when AIDP returns the BindingId; required for unbind. */
  binding_id?: string | null;
  od_id: string;
  od_name?: string | null;
  kds_id: string;
  kds_name?: string | null;
  description?: string | null;
  create_time?: string | null;
}

export interface AidpOntologyBindingListResponse {
  value: AidpOntologyBinding[];
  total_count: number;
  has_more: boolean;
  total_reliable: boolean;
}

export type AidpMetadataFieldType = "string" | "number" | "date";

export interface AidpMetadataExtendedProperty {
  key: string;
  value: string;
}

export interface AidpMetadataDemoTask {
  state: "running" | "success" | "failed";
  label?: string;
}

export interface AidpOntologyMetadataField {
  /** AIDP MetadataId; absent on older responses, which blocks ID-based writes. */
  id?: string | number | null;
  field_name: string;
  field_type: AidpMetadataFieldType;
  column_index?: number | null;
  /** Demo-only values. AIDP has no persistence contract for them. */
  candidates?: string[] | null;
  extended_properties?: AidpMetadataExtendedProperty[] | null;
  /** Demo-only total; AIDP has no per-field chunk count API. */
  associated_chunk_count?: number | null;
  create_time?: string | null;
  update_time?: string | null;
  /** Demo-only mock status; never infer real task state from it. */
  status?: string | null;
  demo_task?: AidpMetadataDemoTask | null;
}

export interface AidpOntologyMetadataFieldListResponse {
  value: AidpOntologyMetadataField[];
  total_count: number;
  has_more: boolean;
  total_reliable: boolean;
  limit: number;
}

export type AidpRuleLogicalOperator = "and" | "or";
export type AidpRuleEffectMode = "multiply" | "add";
export type AidpRuleFieldTransform = "none" | "linear" | "log";

export interface AidpOntologyRuleCondition {
  field: string;
  operator: string;
  value?: string | number | null;
}

export interface AidpOntologyRuleConditionGroup {
  logical_operator: AidpRuleLogicalOperator;
  conditions: AidpOntologyRuleCondition[];
}

export interface AidpOntologyRuleActionValue {
  effect_mode: AidpRuleEffectMode;
  coefficient?: number | null;
  field?: string | null;
  field_scale?: number | null;
  field_transform?: AidpRuleFieldTransform | null;
  field_range?: [number, number] | null;
}

export interface AidpOntologyRuleJsonEnvelope<T> {
  type: "json";
  value: T;
}

export interface AidpOntologyRule {
  rule_id: string;
  name: string;
  description: string;
  enabled: boolean;
  condition: AidpOntologyRuleJsonEnvelope<AidpOntologyRuleConditionGroup>;
  action: AidpOntologyRuleJsonEnvelope<AidpOntologyRuleActionValue>;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface AidpOntologyRuleListResponse {
  value: AidpOntologyRule[];
  total_count: number;
  has_more: boolean;
  total_reliable: boolean;
}

export interface AidpOntologyRulePayload {
  name: string;
  description: string;
  enabled: boolean;
  condition: AidpOntologyRuleJsonEnvelope<AidpOntologyRuleConditionGroup>;
  action: AidpOntologyRuleJsonEnvelope<AidpOntologyRuleActionValue>;
}

export interface AidpOntologyTask {
  task_id: string | null;
  task_type: string | null;
  status: string | null;
  progress: number | null;
  description: string;
  error_message: string;
  start_time: number | string | null;
  end_time: number | string | null;
}

export interface AidpOntologyTaskListResponse {
  value: AidpOntologyTask[];
  total_count: number;
  task_count: number | null;
  has_more: boolean;
  total_reliable: boolean;
}

export interface AidpChunk {
  chunk_id: number | string;
  chunk_text: string;
  chunk_type: string;
  file_name: string;
  file_url: string;
  page_ids: number[];
  metadata: Record<string, unknown>;
}

export interface AidpChunkListResponse {
  value: AidpChunk[];
  total_count: number;
  has_more: boolean;
  total_reliable: boolean;
}

export interface AidpBatchMetadataResult {
  total: number;
  success_count: number;
  failed_count: number;
  /** Confirmed AIDP response reports a partial-failure flag with counters. */
  partial_failure?: boolean;
  success_list: Array<{ chunk_id: number | string }>;
  failed_list: Array<{ chunk_id: number | string; message: string }>;
}

export interface AidpOntologyExportPayload {
  include_properties: boolean;
  include_relations: boolean;
  kind: AidpOntologyKind | null;
}

export interface AidpOntologyAsyncAcknowledgment {
  accepted: true;
  task_id: string | null;
  status?: string | null;
}

export interface AidpOntologyImportError {
  index: number | null;
  type: string | null;
  api_name: string | null;
  message: string;
}

export interface AidpOntologyImportCounts {
  type_count: number;
  entity_count: number;
  relation_count: number;
}

export interface AidpOntologySyncImportResult {
  accepted: false;
  imported_count: number;
  skipped_count: number;
  failed_count: number;
  relation_imported: number;
  relation_failed: number;
  first_error?: unknown;
  errors: AidpOntologyImportError[];
  counts: AidpOntologyImportCounts;
}

export interface AidpOntologySyncExportResult {
  accepted: false;
  domain_name: string;
  data: Record<string, unknown>;
  filename: string;
}

export type AidpOntologyImportResult =
  | AidpOntologySyncImportResult
  | (AidpOntologyAsyncAcknowledgment & { counts: AidpOntologyImportCounts });

export type AidpOntologyExportResult =
  AidpOntologySyncExportResult | AidpOntologyAsyncAcknowledgment;

/** Client-side preview of an uploaded export file, computed before submit. */
export interface AidpOntologyImportPreview {
  fileName: string;
  domainKey: string | null;
  targetDomainName: string;
  typeCount: number;
  entityCount: number;
  relationCount: number;
  errors: Array<{ field: string; message: string }>;
}

/** Raw JSON value accepted from an exported ontology file. */
export type AidpOntologyJsonDocument = Record<string, unknown>;

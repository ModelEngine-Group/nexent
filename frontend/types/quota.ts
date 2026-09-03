// Quota management type definitions

import { ErrorCode } from "@/const/errorCode";

// Tenant-level quota configuration
export interface TenantQuotaConfig {
  hard_limit_bytes: number | null;
  hard_limit_readable: string | null;
  hard_limit_editable: boolean;
  warning_enabled: boolean;
  warning_threshold_pct: number;
  critical_threshold_pct: number;
  summary?: QuotaSummary;
}

// Quota summary allocation vs usage
export interface QuotaSummary {
  soft_allocated_total_bytes: number;
  soft_allocated_readable: string | null;
  hard_limit_bytes: number | null;
  hard_limit_readable: string | null;
  total_bytes: number | null;
  total_readable: string | null;
  oversubscription_ratio: number | null;
  kb_count: number;
  kbs_with_quota: number;
}

// Per-KB breakdown entry in usage response
export interface KBQuotaStatus {
  knowledge_id: number;
  knowledge_name: string;
  index_name: string;
  soft_quota_bytes: number | null;
  soft_quota_readable: string | null;
  actual_bytes: number;
  actual_readable: string | null;
  /** Elasticsearch physical index size; not included in quota usage. */
  es_physical_bytes?: number | null;
  es_physical_readable?: string | null;
  usage_pct: number | null;
  file_count: number;
  kb_warning_level: "normal" | "warning" | "critical" | "exceeded";
}

// Tenant-level usage status
export interface TenantQuotaLevel {
  usage_pct: number | null;
  warning_level: "normal" | "warning" | "critical" | "blocked";
  hard_limit_bytes: number | null;
  hard_limit_readable: string | null;
  total_bytes: number | null;
  total_readable: string | null;
  es_physical_bytes?: number | null;
  es_physical_readable?: string | null;
}

// KB-level usage status
export interface KBQuotaLevel {
  usage_pct: number | null;
  warning_level: "normal" | "warning" | "critical" | "exceeded";
}

// Dual-level quota status from upload response
export interface QuotaStatusResponse {
  warning_enabled?: boolean;
  tenant_level: TenantQuotaLevel;
  kb_level: KBQuotaLevel;
}

// Full usage response
export interface QuotaUsageResponse {
  total_bytes: number;
  total_readable: string | null;
  /** Elasticsearch physical index size, displayed separately from quota usage. */
  es_physical_bytes?: number | null;
  es_physical_readable?: string | null;
  kb_count: number;
  file_count: number;
  hard_limit_bytes: number | null;
  hard_limit_readable: string | null;
  available_bytes: number | null;
  available_readable: string | null;
  usage_pct: number | null;
  tenant_warning_level: "normal" | "warning" | "critical" | "blocked";
  warning_enabled: boolean;
  warning_threshold_pct: number;
  critical_threshold_pct: number;
  breakdown?: KBQuotaStatus[];
  soft_allocated_total_bytes?: number;
  soft_allocated_readable?: string | null;
  oversubscription_ratio?: number | null;
  kbs_with_quota?: number;
}

// Platform-level quota overview
export interface PlatformTenantQuota {
  tenant_id: string;
  tenant_name: string;
  hard_limit_bytes: number | null;
  hard_limit_readable: string | null;
  actual_bytes: number;
  actual_readable: string | null;
  es_physical_bytes?: number | null;
  es_physical_readable?: string | null;
  usage_pct: number | null;
  warning_level: "normal" | "warning" | "critical" | "blocked";
  warning_enabled?: boolean;
}

export interface PlatformQuotaOverview {
  platform_capacity_bytes: number | null;
  platform_capacity_readable: string | null;
  tenants: PlatformTenantQuota[];
  total_allocated_bytes: number;
  total_allocated_readable: string | null;
  total_actual_bytes: number;
  total_actual_readable: string | null;
  total_es_physical_bytes?: number | null;
  total_es_physical_readable?: string | null;
  tenant_count: number;
  oversubscription_ratio: number | null;
  remaining_allocatable_bytes: number | null;
  remaining_allocatable_readable: string | null;
  allocation_percentage: number | null;
  unmanaged_tenant_count: number;
  capacity_management_enforced: boolean;
}

// Request payloads
export interface UpdateTenantQuotaPayload {
  hard_limit_gb?: number | null;
  /** For testing with small quotas: set limit in MB instead of GB. */
  hard_limit_mb?: number | null;
  warning_enabled?: boolean;
  warning_threshold_pct?: number;
  critical_threshold_pct?: number;
}

export interface UpdatePlatformCapacityPayload {
  capacity_gb: number | null;
}

export interface UpdateTenantHardQuotaPayload {
  hard_limit_gb?: number | null;
  /** For testing with small quotas: set limit in MB instead of GB. */
  hard_limit_mb?: number | null;
}

// Personal KB capacity management (ADMIN/SU)
export type PersonalQuotaSource = "individual" | "default" | "unlimited";

export interface PersonalCapacityUser {
  user_id: string;
  user_name: string;
  email: string | null;
  kb_count: number;
  total_bytes: number;
  total_readable: string | null;
  es_physical_bytes?: number | null;
  es_physical_readable?: string | null;
  usage_rate: number | null;
  quota_limit_bytes: number | null;
  quota_limit_readable: string | null;
  effective_quota_bytes: number | null;
  effective_quota_readable: string | null;
  quota_source: PersonalQuotaSource;
}

export interface PersonalCapacityUsersResponse {
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  items: PersonalCapacityUser[];
}

export interface PersonalKnowledgeBaseItem {
  kb_id: number | string;
  knowledge_id: number | string;
  index_name: string;
  name: string;
  source: string | null;
  doc_count: number;
  chunk_count: number;
  store_size: string | null;
  store_size_bytes: number;
  /** Explicit aliases for the ES physical index metric. */
  es_physical_size?: string | null;
  es_physical_size_bytes?: number;
  source_size?: string | null;
  source_size_bytes?: number;
  total_size?: string | null;
  total_size_bytes?: number;
  quota_limit_bytes: number | null;
  quota_limit_readable: string | null;
  updated_at: string | null;
}

export interface PersonalKbDetailResponse {
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  kbs: PersonalKnowledgeBaseItem[];
}

export interface PersonalQuotaPayload {
  quota_limit_bytes?: number | null;
  unlimited?: boolean;
}

export interface PersonalDefaultQuota {
  quota_limit_bytes: number | null;
  quota_limit_readable: string | null;
  unlimited: boolean;
}

export interface PersonalCapacitySummary {
  user_count: number;
  kb_count: number;
  total_bytes: number;
  total_readable: string | null;
  total_es_physical_bytes?: number | null;
  total_es_physical_readable?: string | null;
  allocated_quota_bytes: number;
  allocated_quota_readable: string | null;
  default_quota_bytes: number | null;
  default_quota_readable: string | null;
}

export type PersonalSelfQuotaSource = "individual" | "default" | "unlimited";

export interface PersonalSelfCapacity {
  used_bytes: number;
  used_readable: string | null;
  es_physical_bytes?: number | null;
  es_physical_readable?: string | null;
  quota_bytes: number | null;
  quota_readable: string | null;
  quota_source: PersonalSelfQuotaSource;
  usage_rate: number | null;
  is_over_quota: boolean;
  kb_count: number;
}

// ── Error types ──────────────────────────────────────────────

const QUOTA_CONFLICT_TRANSLATION_KEYS: Record<string, string> = {
  PlatformCapacityExceeded: "quota.error.platformCapacityExceeded",
  PlatformCapacityBelowAllocation:
    "quota.error.platformCapacityBelowAllocation",
  TenantQuotaBelowUsage: "quota.error.tenantQuotaBelowUsage",
  [ErrorCode.TENANT_PERSONAL_KB_QUOTA_BELOW_USAGE]:
    "tenantResources.personalCapacity.quotaBelowUsageWarning",
};

/** Return the translation key for a known quota allocation conflict. */
export function getQuotaConflictTranslationKey(
  error: unknown
): string | undefined {
  if (!error || typeof error !== "object" || !("code" in error)) {
    return undefined;
  }
  const code = (error as { code?: unknown }).code;
  return typeof code === "string"
    ? QUOTA_CONFLICT_TRANSLATION_KEYS[code]
    : undefined;
}

/** Detects if an HTTP error response indicates tenant storage is full (HTTP 413). */
export function isQuotaExceededError(status: number, body: any): boolean {
  return status === 413 && body?.error === "TenantStorageFull";
}

/** Extract user-friendly quota exceeded message from error body. */
export function getQuotaExceededMessage(body: any): string {
  if (!body) return "Storage limit reached";
  const usage = body.usage_bytes
    ? `${(body.usage_bytes / 1024 ** 3).toFixed(1)} GB`
    : "unknown";
  const limit = body.hard_limit_bytes
    ? `${(body.hard_limit_bytes / 1024 ** 3).toFixed(1)} GB`
    : "unknown";
  const exceeded = body.exceeded_by_bytes
    ? `${(body.exceeded_by_bytes / 1024 ** 3).toFixed(1)} GB`
    : "unknown";
  return `Tenant storage full: ${usage} used of ${limit} limit (exceeded by ${exceeded})`;
}

// Quota management type definitions

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

// ── Error types ──────────────────────────────────────────────

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

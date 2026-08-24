export interface ModelMonitoringItem {
  model_id: number | null;
  model_name: string;
  model_type: string;
  display_name: string;
  request_count: number;
  error_rate: number;
  avg_duration: number;
  avg_ttft: number;
  token_generation_rate: number;
  total_tokens: number;
}

export interface MonitoringFilter {
  time_range?: string;
  page?: number;
  page_size?: number;
}

export interface MonitoringStatus {
  telemetry_enabled: boolean;
  provider: string;
  dashboard_url?: string | null;
  dashboard_port?: string | number | null;
  dashboard_path?: string | null;
}

export interface ContextBudgetMonitoringItem {
  provider_protocol: string;
  model_name: string;
  capability_profile_version: string;
  request_count: number;
  overflow_count: number;
  overflow_rate: number | null;
  compacted_count: number;
  compaction_incidence: number | null;
  avg_compression_ratio: number | null;
  estimate_sample_count: number;
  mean_absolute_estimate_error: number | null;
  recovery_attempt_count: number;
  recovery_success_count: number;
  recovery_success_rate: number | null;
}

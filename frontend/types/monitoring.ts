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

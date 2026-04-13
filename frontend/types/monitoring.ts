export interface ModelMonitoringItem {
  model_id: string;
  model_name: string;
  display_name: string;
  request_count: number;
  error_rate: number;
  failure_rate: number;
  avg_duration: number;
  avg_ttft: number;
  total_tokens: number;
  total_cost: number;
  quality_score: number;
}

export interface ModelPerformanceDetail {
  total_requests: number;
  error_rate: number;
  failure_rate: number;
  avg_duration: number;
  p50_duration: number;
  p95_duration: number;
  p99_duration: number;
  avg_ttft: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  total_cost: number;
  today_cost: number;
  quality_avg_score: number;
  quality_positive_ratio: number;
}

export interface ErrorBreakdown {
  error_type: string;
  count: number;
  percentage: number;
  is_recoverable: boolean;
}

export interface TrendPoint {
  timestamp: string;
  request_count: number;
  error_rate: number;
  failure_rate: number;
  avg_duration: number;
  cost: number;
  tokens: number;
}

export interface FailureDetail {
  id: string;
  timestamp: string;
  model_name: string;
  failure_type: string;
  error_message: string;
  request_duration: number;
  status_code: number;
}

export interface AlertRecord {
  id: string;
  type: string;
  severity: string;
  model_name: string;
  message: string;
  threshold: number;
  current_value: number;
  status: string;
  created_at: string;
  acknowledged_at?: string;
  resolved_at?: string;
}

export interface MonitoringResponse<T> {
  code: number;
  message: string;
  data: T;
}

export interface PaginatedData<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface ModelSummaryResponse {
  performance: ModelPerformanceDetail;
  error_breakdown: ErrorBreakdown[];
}

export interface MonitoringFilter {
  time_range?: string;
  page?: number;
  page_size?: number;
}

export interface TrendFilter {
  interval?: string;
  time_range?: string;
}

export interface AlertFilter {
  status?: string;
  severity?: string;
  type?: string;
  page?: number;
  page_size?: number;
}

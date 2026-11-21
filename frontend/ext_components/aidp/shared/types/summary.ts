// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/** AIDP file summary states documented for the 2026-11 contract. */
export type AidpSummaryStatus = "pending" | "success" | "failed";

/** One file's summary as returned inside AIDP's `result` object. */
export interface AidpFileSummary {
  summary_status?: AidpSummaryStatus | string;
  summary_text?: string;
  summary_model?: string;
  /** Failure reason from AIDP's file_summary_table; filled only when failed. */
  error_reason?: string;
  /** Unknown diagnostic fields are preserved for display/debugging only. */
  [key: string]: unknown;
}

export interface AidpFileSummaryResponse {
  result: AidpFileSummary;
}

/** One entry in a RetrySummary success/failure list. */
export interface AidpSummaryRetryItem {
  file_uuid?: string;
  err_code?: string | number | null;
  code?: string | number | null;
  message?: string | null;
  reason?: string | null;
  [key: string]: unknown;
}

export interface AidpSummaryRetryResponse {
  /** Files whose retry was accepted; may be a partial subset of the request. */
  partial_success_list?: Array<AidpSummaryRetryItem | string>;
  failed_list?: Array<AidpSummaryRetryItem | string>;
  [key: string]: unknown;
}

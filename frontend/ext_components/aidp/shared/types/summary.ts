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

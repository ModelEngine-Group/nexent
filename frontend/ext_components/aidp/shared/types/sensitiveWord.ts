// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/** AIDP sensitive word dictionary modes. */
export type AidpSensitiveWordMode = "BLACK" | "WHITE";

/** Built-in words are read-only in the AIDP dictionary. */
export type AidpSensitiveWordSource = "BUILT_IN" | "CUSTOM";

export interface AidpSensitiveWordItem {
  id: string;
  word: string;
  mode: AidpSensitiveWordMode;
  description: string;
  source: AidpSensitiveWordSource;
  create_time?: number | null;
  update_time?: number | null;
}

export interface AidpSensitiveWordListResponse {
  value: AidpSensitiveWordItem[];
  /** Upstream page link. It may omit the active mode/keyword filters. */
  next_link?: string | null;
  total_count: number;
}

export interface AidpSensitiveWordPayload {
  word: string;
  mode: AidpSensitiveWordMode;
  description: string;
}

export type AidpSensitiveWordUpdatePayload = Partial<AidpSensitiveWordPayload>;

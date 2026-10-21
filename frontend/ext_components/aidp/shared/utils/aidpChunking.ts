// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/** AIDP defaults shared by the create page and the detail settings. */
export const AIDP_DEFAULT_CHUNK_TOKEN_NUM = 512;
export const AIDP_DEFAULT_CHUNK_OVERLAP_PERCENT = 10;
export const AIDP_DEFAULT_SIMILARITY = 0;
export const AIDP_DEFAULT_TOPK = 10;

export const AIDP_CHUNK_TOKEN_MIN = 256;
export const AIDP_CHUNK_TOKEN_MAX = 4096;
export const AIDP_OVERLAP_PERCENT_MIN = 1;
export const AIDP_OVERLAP_PERCENT_MAX = 40;

/** AIDP stores overlap as an integer token count, not as a percentage. */
export const chunkOverlapTokens = (
  chunkTokenNum: number,
  overlapPercent: number
): number => Math.round((chunkTokenNum * overlapPercent) / 100);

export const chunkOverlapPercent = (
  chunkTokenNum: number | null | undefined,
  overlapNum: number | null | undefined
): number | null => {
  if (
    typeof chunkTokenNum !== "number" ||
    typeof overlapNum !== "number" ||
    chunkTokenNum <= 0
  ) {
    return null;
  }
  return (overlapNum / chunkTokenNum) * 100;
};

/** Formats the stored token overlap as the percentage shown in the UI. */
export const formatChunkOverlapPercent = (
  chunkTokenNum: number | null | undefined,
  overlapNum: number | null | undefined
): string | null => {
  const percent = chunkOverlapPercent(chunkTokenNum, overlapNum);
  return percent === null ? null : `${percent.toFixed(1)}%`;
};

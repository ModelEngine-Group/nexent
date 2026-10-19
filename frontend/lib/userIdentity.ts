// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/** Format an identity without changing its raw value or caller's fallback. */
export function getUserDisplayName(
  authProvider: string | undefined,
  casUsername: string | null | undefined,
  fallback: string
): string {
  return authProvider === "cas" && casUsername?.trim()
    ? casUsername.trim()
    : fallback;
}

// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/** Only return through history when its entry came from this application. */
export function canReturnToAgentEditorReferrer(
  historyLength: number,
  referrer: string,
  origin: string
): boolean {
  if (historyLength <= 1 || !referrer) return false;
  try {
    return new URL(referrer).origin === origin;
  } catch {
    return false;
  }
}

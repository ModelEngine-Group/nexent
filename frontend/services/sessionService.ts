// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import {
  canRefreshLocalSession,
  checkSessionValid,
  getTokenExpiresAt,
  handleSessionExpired,
} from "@/lib/session";
import { API_ENDPOINTS } from "@/services/api";
import type { Session } from "@/types/auth";

export function withLocalSessionLock<T>(
  callback: () => Promise<T>
): Promise<T> {
  return typeof navigator !== "undefined" && navigator.locks
    ? navigator.locks.request("nexent-local-session", callback)
    : callback();
}

let pendingAttempt: { expiresAt: number; id: string } | undefined;
let inFlight: Promise<Session | null> | undefined;

async function refresh(): Promise<Session | null> {
  const expiresAt = getTokenExpiresAt();
  if (expiresAt === null || !checkSessionValid() || !canRefreshLocalSession())
    return null;

  const attempt =
    pendingAttempt?.expiresAt === expiresAt
      ? pendingAttempt
      : {
          expiresAt,
          id: Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) =>
            byte.toString(16).padStart(2, "0")
          ).join(""),
        };
  pendingAttempt = attempt;

  const response = await fetch(API_ENDPOINTS.user.refreshToken, {
    method: "POST",
    headers: { "X-Refresh-Request-Id": attempt.id },
  });
  if (
    response.status === 401 &&
    getTokenExpiresAt() === expiresAt &&
    canRefreshLocalSession()
  ) {
    pendingAttempt = undefined;
    handleSessionExpired();
  }
  if (!response.ok) return null;
  const { data } = await response.json();
  pendingAttempt = undefined;
  return data?.session ?? null;
}

export const sessionService = {
  refreshToken: (): Promise<Session | null> => {
    inFlight ??= refresh().finally(() => {
      inFlight = undefined;
    });
    return inFlight;
  },
};

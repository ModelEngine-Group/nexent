// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { STORAGE_KEYS } from "@/const/auth";
import {
  checkSessionValid,
  getSessionScope,
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

type RefreshAttempt = { scope: string; expiresAt: number; id: string };
let pendingAttempt: RefreshAttempt | undefined;
let inFlight: Promise<Session | null> | undefined;
let unavailableScope: string | undefined;

function persistAttempt(attempt?: RefreshAttempt): void {
  pendingAttempt = attempt;
  try {
    if (attempt)
      sessionStorage.setItem(
        STORAGE_KEYS.REFRESH_ATTEMPT,
        JSON.stringify(attempt)
      );
    else sessionStorage.removeItem(STORAGE_KEYS.REFRESH_ATTEMPT);
  } catch {
    // Private contexts may deny storage; retries in the same document still work.
  }
}

function matchingAttempt(
  scope: string,
  expiresAt: number | null
): RefreshAttempt | undefined {
  let attempt = pendingAttempt;
  if (!attempt) {
    try {
      attempt = JSON.parse(
        sessionStorage.getItem(STORAGE_KEYS.REFRESH_ATTEMPT) ?? "null"
      );
    } catch {
      // Treat inaccessible or malformed storage as an absent attempt.
    }
  }
  if (
    attempt?.scope === scope &&
    attempt.expiresAt === expiresAt &&
    /^[0-9a-f]{32}$/.test(attempt.id)
  ) {
    return attempt;
  }
  persistAttempt();
  return undefined;
}

async function refresh(): Promise<Session | null> {
  const scope = getSessionScope();
  const expiresAt = getTokenExpiresAt();
  const previous = matchingAttempt(scope, expiresAt);
  if (expiresAt === null || !checkSessionValid() || scope === unavailableScope)
    return null;

  const attempt = previous ?? {
    scope,
    expiresAt,
    id: Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) =>
      byte.toString(16).padStart(2, "0")
    ).join(""),
  };
  persistAttempt(attempt);

  const response = await fetch(API_ENDPOINTS.user.refreshToken, {
    method: "POST",
    headers: { "X-Refresh-Request-Id": attempt.id },
  });
  // A different login may have completed while this request was in flight.
  if (getSessionScope() !== scope) {
    matchingAttempt(getSessionScope(), getTokenExpiresAt());
    return null;
  }
  if (response.status === 204) {
    unavailableScope = scope;
    persistAttempt();
    return null;
  }
  if (response.status === 401 && getTokenExpiresAt() === expiresAt) {
    persistAttempt();
    handleSessionExpired();
  }
  if (!response.ok) return null;
  persistAttempt();
  const { data } = await response.json();
  return data?.session ?? null;
}

export const sessionService = {
  discardPreviousRefreshAttempt: (): void => {
    matchingAttempt(getSessionScope(), getTokenExpiresAt());
  },
  refreshToken: (): Promise<Session | null> => {
    inFlight ??= refresh().finally(() => {
      inFlight = undefined;
    });
    return inFlight;
  },
};

const DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 300;
const MIN_HEARTBEAT_INTERVAL_MS = 1_000;
const HEARTBEAT_STORAGE_PREFIX = "nexent:cas-heartbeat:last-attempt:";
const HEARTBEAT_LOCK_PREFIX = "nexent:cas-heartbeat:lock:";

export interface CasHeartbeatAttemptState {
  url: string;
  attemptedAt: number;
}

export const getHeartbeatIntervalMs = (intervalSeconds: number): number => {
  const normalizedSeconds =
    Number.isFinite(intervalSeconds) && intervalSeconds > 0
      ? intervalSeconds
      : DEFAULT_HEARTBEAT_INTERVAL_SECONDS;
  return Math.max(MIN_HEARTBEAT_INTERVAL_MS, normalizedSeconds * 1_000);
};

export const isHeartbeatDue = (
  lastAttemptAt: number,
  now: number,
  intervalMs: number
): boolean => lastAttemptAt <= 0 || now - lastAttemptAt >= intervalMs;

export const buildHeartbeatAuthHeader = (
  cookieString: string,
  cookieName: string
): string | null => {
  const normalizedName = cookieName.trim();
  if (!normalizedName) return null;

  for (const cookiePart of cookieString.split(";")) {
    const separatorIndex = cookiePart.indexOf("=");
    if (separatorIndex < 0) continue;

    const name = cookiePart.slice(0, separatorIndex).trim();
    if (name !== normalizedName) continue;

    const value = cookiePart.slice(separatorIndex + 1).trim();
    return `${normalizedName}=${value}`;
  }

  return null;
};

export const getHeartbeatStorageKey = (userId: string): string =>
  `${HEARTBEAT_STORAGE_PREFIX}${userId}`;

export const getHeartbeatLockName = (userId: string): string =>
  `${HEARTBEAT_LOCK_PREFIX}${userId}`;

export const readHeartbeatAttempt = (
  userId: string
): CasHeartbeatAttemptState | null => {
  if (typeof window === "undefined") return null;

  try {
    const value = window.localStorage.getItem(getHeartbeatStorageKey(userId));
    if (!value) return null;

    const parsed = JSON.parse(value) as Partial<CasHeartbeatAttemptState>;
    if (
      typeof parsed.url !== "string" ||
      typeof parsed.attemptedAt !== "number" ||
      !Number.isFinite(parsed.attemptedAt)
    ) {
      return null;
    }
    return { url: parsed.url, attemptedAt: parsed.attemptedAt };
  } catch {
    return null;
  }
};

export const writeHeartbeatAttempt = (
  userId: string,
  state: CasHeartbeatAttemptState
): void => {
  if (typeof window === "undefined") return;

  try {
    window.localStorage.setItem(
      getHeartbeatStorageKey(userId),
      JSON.stringify(state)
    );
  } catch {
    // In-memory throttling in the session manager remains active when storage is unavailable.
  }
};

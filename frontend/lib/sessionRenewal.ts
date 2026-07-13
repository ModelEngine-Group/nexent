export type SessionRenewalAction = "none" | "refresh-local" | "renew-cas";

interface SessionRenewalDecision {
  authProvider?: "local" | "cas";
  isVisible: boolean;
  remainingLifetimeMs: number;
  localRefreshThresholdMs: number;
  currentTimeMs: number;
  lastCasRenewAttemptAtMs: number;
  casRenewIntervalMs: number;
  casRenewSafetyWindowMs: number;
  isCasRenewing: boolean;
  hasCasRenewAttempted: boolean;
}

export function getSessionRenewalAction({
  authProvider,
  isVisible,
  remainingLifetimeMs,
  localRefreshThresholdMs,
  currentTimeMs,
  lastCasRenewAttemptAtMs,
  casRenewIntervalMs,
  casRenewSafetyWindowMs,
  isCasRenewing,
  hasCasRenewAttempted,
}: SessionRenewalDecision): SessionRenewalAction {
  if (!isVisible || remainingLifetimeMs <= 0) return "none";

  if (authProvider === "cas") {
    if (isCasRenewing) return "none";

    const intervalElapsed =
      currentTimeMs - lastCasRenewAttemptAtMs >=
      Math.max(1_000, casRenewIntervalMs);
    const withinSafetyWindow =
      remainingLifetimeMs <= Math.max(1_000, casRenewSafetyWindowMs);
    const safetyRenewalDue = withinSafetyWindow && !hasCasRenewAttempted;
    return intervalElapsed || safetyRenewalDue ? "renew-cas" : "none";
  }

  return remainingLifetimeMs <= localRefreshThresholdMs
    ? "refresh-local"
    : "none";
}

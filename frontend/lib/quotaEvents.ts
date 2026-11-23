export const QUOTA_USAGE_CHANGED_EVENT = "quotaUsageChanged";

export function emitQuotaUsageChanged(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(QUOTA_USAGE_CHANGED_EVENT));
}

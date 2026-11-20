// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

export function getAgentPublishCompletion({
  success,
}: {
  success: boolean;
  data?: unknown;
}): "complete" | "stay" {
  return success ? "complete" : "stay";
}

export function getAgentUsageGuideAccess({
  currentVersionNo,
  permission,
}: {
  currentVersionNo?: number | null;
  permission?: string | null;
}): { canOpen: boolean; canManageShare: boolean } {
  return {
    canOpen: (currentVersionNo ?? 0) > 0,
    canManageShare: permission !== "READ_ONLY",
  };
}

export type AgentDeepLinkAction<T> =
  | { action: "ignore" }
  | { action: "wait" }
  | { action: "select"; agent: T }
  | { action: "dismiss" };

export function resolveAgentDeepLinkAction<T>({
  agentId,
  agents,
  consumed,
  isLoading,
  getAgentId,
}: {
  agentId: number | null;
  agents: readonly T[];
  consumed: boolean;
  isLoading: boolean;
  getAgentId: (agent: T) => number | null;
}): AgentDeepLinkAction<T> {
  if (agentId == null || consumed) {
    return { action: "ignore" };
  }
  if (isLoading) {
    return { action: "wait" };
  }
  const agent = agents.find((candidate) => getAgentId(candidate) === agentId);
  return agent ? { action: "select", agent } : { action: "dismiss" };
}

export function buildAgentShareUrl(
  origin: string,
  locale: string,
  agentId: number
): string {
  return `${origin.replace(/\/+$/, "")}/${locale}/newchat?agent_id=${encodeURIComponent(agentId)}`;
}

export function buildDefaultAgentVersionName(
  agentDisplayName: string | null | undefined,
  now: Date = new Date()
): string {
  const trimmedName = (agentDisplayName || "").trim();
  const timestamp = [
    String(now.getFullYear()).slice(-2),
    String(now.getMonth() + 1).padStart(2, "0"),
    String(now.getDate()).padStart(2, "0"),
    String(now.getHours()).padStart(2, "0"),
    String(now.getMinutes()).padStart(2, "0"),
  ].join("");
  return trimmedName ? `${trimmedName}-${timestamp}` : timestamp;
}

export function buildAuthenticationReturnPath(
  pathname: string,
  search: string
): string {
  const query = search.replace(/^\?/, "");
  return query ? `${pathname}?${query}` : pathname;
}

export function buildCopyAriaLabel(
  copyLabel: string,
  fieldLabel: string
): string {
  return `${copyLabel} ${fieldLabel}`;
}

export function isAnonymousConversationSharePath(pathname: string): boolean {
  return pathname.startsWith("/share/");
}

export function buildNorthboundRunUrl(northboundBaseUrl?: string): string {
  const baseUrl = northboundBaseUrl?.trim().replace(/\/+$/, "");
  return `${baseUrl || "http://localhost:5013/api"}/nb/v1/chat/run`;
}

export function buildUserApiKeyPath(locale: string): string {
  return `/${locale}/users`;
}

export function buildNorthboundDocsUrl(locale: string): string {
  return `https://modelengine-group.github.io/nexent/${locale}/integration/integration-out/northbound-api.html`;
}

export function getA2AGuideState({
  isLoading,
  isError,
  isEnabled,
}: {
  isLoading: boolean;
  isError: boolean;
  isEnabled: boolean;
}): "loading" | "error" | "enabled" | "disabled" {
  if (isLoading) return "loading";
  if (isError) return "error";
  return isEnabled ? "enabled" : "disabled";
}

export function buildNorthboundCurl(agentName: string, runUrl: string): string {
  const payload = JSON.stringify({
    agent_name: agentName,
    query: "Hello",
  }).replaceAll("'", "'\\''");
  return [
    `curl -N -X POST '${runUrl}'`,
    "  -H 'Authorization: Bearer <YOUR_API_KEY>'",
    "  -H 'Content-Type: application/json'",
    `  -d '${payload}'`,
  ].join(" \\\n");
}

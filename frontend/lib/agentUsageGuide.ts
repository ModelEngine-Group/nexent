export function buildAgentUsageGuidePath(
  locale: string,
  agentId: number
): string {
  return `/${locale}/agent-space?tab=mine&agent_id=${agentId}&guide=usage`;
}

export function clearAgentUsageGuidePath(
  locale: string,
  agentId: number
): string {
  return `/${locale}/agent-space?tab=mine&agent_id=${agentId}`;
}

export function parseAgentUsageGuideParams(
  searchParams: Pick<URLSearchParams, "get">
): { agentId: number } | null {
  if (searchParams.get("guide") !== "usage") {
    return null;
  }

  const agentId = Number(searchParams.get("agent_id"));
  return Number.isSafeInteger(agentId) && agentId > 0 ? { agentId } : null;
}

export type AgentUsageGuideTargetState<T> =
  | { state: "loading" }
  | { state: "missing" }
  | { state: "found"; agent: T };

export function resolveAgentUsageGuideTarget<T>({
  agentId,
  agents,
  fallbackAgent,
  isListLoading,
  isFallbackLoading,
  getAgentId,
}: {
  agentId: number;
  agents: readonly T[];
  fallbackAgent: T | null;
  isListLoading: boolean;
  isFallbackLoading: boolean;
  getAgentId: (agent: T) => number | null;
}): AgentUsageGuideTargetState<T> {
  const agentFromList = agents.find((agent) => getAgentId(agent) === agentId);
  if (agentFromList) {
    return { state: "found", agent: agentFromList };
  }
  if (fallbackAgent && getAgentId(fallbackAgent) === agentId) {
    return { state: "found", agent: fallbackAgent };
  }
  if (isListLoading || isFallbackLoading) {
    return { state: "loading" };
  }
  return { state: "missing" };
}

export function getAgentUsageGuideOpenAction<T>({
  agentId,
  consumedAgentId,
  target,
}: {
  agentId: number;
  consumedAgentId: number | null;
  target: AgentUsageGuideTargetState<T>;
}):
  | { action: "ignore" }
  | { action: "wait" }
  | { action: "missing" }
  | { action: "open"; agent: T } {
  if (consumedAgentId === agentId) {
    return { action: "ignore" };
  }
  if (target.state === "loading") {
    return { action: "wait" };
  }
  if (target.state === "missing") {
    return { action: "missing" };
  }
  return { action: "open", agent: target.agent };
}

export function buildAgentShareUrl(
  origin: string,
  locale: string,
  shareToken: string
): string {
  return `${origin.replace(/\/+$/, "")}/${locale}/share/agent/${encodeURIComponent(shareToken)}`;
}

export function isAgentSharePath(pathname: string): boolean {
  return /^\/share\/agent\/[^/]+\/?$/.test(pathname);
}

export function isAnonymousConversationSharePath(pathname: string): boolean {
  return pathname.startsWith("/share/") && !isAgentSharePath(pathname);
}

export function buildNorthboundRunUrl(northboundBaseUrl?: string): string {
  const baseUrl = northboundBaseUrl?.trim().replace(/\/+$/, "");
  return `${baseUrl || "<NEXENT_BASE_URL>"}/nb/v1/chat/run`;
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

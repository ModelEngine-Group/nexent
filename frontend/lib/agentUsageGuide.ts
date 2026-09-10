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

export function buildAgentShareUrl(
  origin: string,
  locale: string,
  shareToken: string
): string {
  return `${origin.replace(/\/+$/, "")}/${locale}/share/agent/${encodeURIComponent(shareToken)}`;
}

export function buildNorthboundRunUrl(northboundBaseUrl?: string): string {
  const baseUrl = northboundBaseUrl?.trim().replace(/\/+$/, "");
  return `${baseUrl || "<NEXENT_BASE_URL>"}/nb/v1/chat/run`;
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

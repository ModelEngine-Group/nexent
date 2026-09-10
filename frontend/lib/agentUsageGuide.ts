export function buildAgentUsageGuidePath(locale: string, agentId: number): string {
  return `/${locale}/agent-space?tab=mine&agent_id=${agentId}&guide=usage`;
}

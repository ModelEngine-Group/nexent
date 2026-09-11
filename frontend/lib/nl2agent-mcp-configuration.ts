export interface McpConfigurationRequest {
  agentId: number;
  cardKey: string;
  requirementId: string;
  requestId: number;
  completed: boolean;
}

export function createMcpConfigurationRequest(
  current: McpConfigurationRequest | null,
  agentId: number,
  cardKey: string,
  requirementId: string
): McpConfigurationRequest {
  return {
    agentId,
    cardKey,
    requirementId,
    requestId: (current?.requestId ?? 0) + 1,
    completed: false,
  };
}

export function completeMcpConfigurationRequest(
  current: McpConfigurationRequest | null,
  agentId: number,
  requestId: number
): McpConfigurationRequest | null {
  if (current?.agentId !== agentId || current.requestId !== requestId) {
    return current;
  }
  return { ...current, completed: true };
}

const completedInMemory = new Set<string>();
const GUIDE_VERSION = "v1";

export function agentCreationGuideKey(tenantId: string, userId: string) {
  return `nexent.agent.creation-guide.${GUIDE_VERSION}/${encodeURIComponent(tenantId)}/${encodeURIComponent(userId)}`;
}

export function canStartAgentCreationGuide({
  creationEntry,
  ready,
  readOnly,
  tenantId,
  userId,
}: {
  creationEntry: boolean;
  ready: boolean;
  readOnly: boolean;
  tenantId?: string | null;
  userId?: string | null;
}) {
  return creationEntry && ready && !readOnly && Boolean(tenantId && userId);
}

export function hasCompletedAgentCreationGuide(key: string) {
  try {
    return (
      completedInMemory.has(key) || window.localStorage.getItem(key) === "1"
    );
  } catch {
    return completedInMemory.has(key);
  }
}

export function completeAgentCreationGuide(key: string) {
  completedInMemory.add(key);
  try {
    window.localStorage.setItem(key, "1");
  } catch {
    // A denied browser preference must not prevent editing the draft.
  }
}

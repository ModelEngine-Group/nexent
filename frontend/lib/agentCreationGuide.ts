// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { isGuideDismissed, setGuideDismissed } from "@/lib/guidePreferences";
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

function sharedKey(key: string) {
  return key.replace(
    "nexent.agent.creation-guide.v1/",
    "nexent.guide-preferences.v1/"
  );
}

export function hasCompletedAgentCreationGuide(key: string) {
  return isGuideDismissed(sharedKey(key), "agent-creation", key);
}

export function completeAgentCreationGuide(key: string) {
  setGuideDismissed(sharedKey(key), "agent-creation", true);
}

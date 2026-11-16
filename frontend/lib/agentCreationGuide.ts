// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  isGuideDismissed,
  setGuideDismissed,
  sharedGuideKey,
  LEGACY_GUIDE_PREFIX,
} from "@/lib/guidePreferences";

export function agentCreationGuideKey(tenantId: string, userId: string) {
  return `${LEGACY_GUIDE_PREFIX}${encodeURIComponent(tenantId)}/${encodeURIComponent(userId)}`;
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
  return isGuideDismissed(sharedGuideKey(key), "agent-creation", key);
}

export function completeAgentCreationGuide(key: string) {
  setGuideDismissed(sharedGuideKey(key), "agent-creation", true);
}

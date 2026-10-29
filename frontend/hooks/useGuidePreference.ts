// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useCallback, useContext, useSyncExternalStore } from "react";
import { AuthorizationContext } from "@/components/providers/AuthorizationProvider";
import {
  guidePreferenceKey,
  isGuideDismissed,
  setGuideDismissed,
  type GuideId,
} from "@/lib/guidePreferences";

function subscribe(notify: () => void) {
  window.addEventListener("storage", notify);
  window.addEventListener("nexent-guide-preferences", notify);
  return () => {
    window.removeEventListener("storage", notify);
    window.removeEventListener("nexent-guide-preferences", notify);
  };
}

export function useGuidePreference(id: GuideId, preferenceKey?: string) {
  const user = useContext(AuthorizationContext)?.user;
  const key =
    preferenceKey?.replace(
      "nexent.agent.creation-guide.v1/",
      "nexent.guide-preferences.v1/"
    ) ??
    (user?.tenantId && user.id
      ? guidePreferenceKey(user.tenantId, user.id)
      : null);
  const legacyKey =
    preferenceKey ??
    (user?.tenantId && user.id
      ? `nexent.agent.creation-guide.v1/${encodeURIComponent(user.tenantId)}/${encodeURIComponent(user.id)}`
      : undefined);
  const dismissed = useSyncExternalStore(
    subscribe,
    () =>
      key
        ? isGuideDismissed(
            key,
            id,
            id === "agent-creation" ? legacyKey : undefined
          )
        : true,
    () => true
  );
  const update = useCallback(
    (value: boolean) => {
      if (key) setGuideDismissed(key, id, value);
    },
    [key, id]
  );
  const dismiss = useCallback(() => update(true), [update]);
  const reset = useCallback(() => update(false), [update]);
  return {
    dismissed,
    ready: Boolean(key),
    dismiss,
    reset,
  };
}

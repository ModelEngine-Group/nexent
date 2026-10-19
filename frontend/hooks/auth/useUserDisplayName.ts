// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";

import { useCallback } from "react";

import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { getUserDisplayName } from "@/lib/userIdentity";

/** Derive names from the current viewer, retaining raw records and form values. */
export function useUserDisplayName() {
  const { user } = useAuthorizationContext();
  const provider = user?.authProvider;
  return useCallback(
    (casUsername: string | null | undefined, fallback: string) =>
      getUserDisplayName(provider, casUsername, fallback),
    [provider]
  );
}

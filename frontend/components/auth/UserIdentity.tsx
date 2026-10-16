// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";

import { useUserDisplayName } from "@/hooks/auth/useUserDisplayName";

interface UserIdentityProps {
  casUsername?: string | null;
  fallback: string;
}

/** A text-only view of an identity; selection and mutation data stay untouched. */
export function UserIdentity({ casUsername, fallback }: UserIdentityProps) {
  const displayName = useUserDisplayName();
  return <>{displayName(casUsername, fallback)}</>;
}

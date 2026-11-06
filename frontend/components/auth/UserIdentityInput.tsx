// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";

import { Input } from "antd";
import type { InputProps } from "antd";

import { useUserDisplayName } from "@/hooks/auth/useUserDisplayName";

/** Present a disabled identity field while Form retains its original value. */
export function UserIdentityInput({
  casUsername,
  value,
  ...props
}: InputProps & { casUsername?: string | null }) {
  const displayName = useUserDisplayName();
  return (
    <Input {...props} value={displayName(casUsername, String(value ?? ""))} />
  );
}

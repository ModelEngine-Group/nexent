// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";

import { useTranslation } from "react-i18next";

import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";

interface UserIdentityLabelProps {
  emailLabelKey: string;
  usernameLabelKey?: string;
}

export function UserIdentityLabel({
  emailLabelKey,
  usernameLabelKey = "common.username",
}: UserIdentityLabelProps) {
  const { user } = useAuthorizationContext();
  const { t } = useTranslation("common");
  return (
    <>{t(user?.authProvider === "cas" ? usernameLabelKey : emailLabelKey)}</>
  );
}

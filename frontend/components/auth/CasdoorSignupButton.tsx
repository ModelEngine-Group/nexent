// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useQuery } from "@tanstack/react-query";
import { Button } from "antd";
import { UserRoundPlus } from "lucide-react";
import { useTranslation } from "react-i18next";

import { oauthService } from "@/services/oauthService";

export function CasdoorSignupButton() {
  const { t } = useTranslation("common");
  const { data: config } = useQuery({
    queryKey: ["oauth", "config"],
    queryFn: () => oauthService.getConfig(),
  });
  const available =
    config?.enabled &&
    config.login_mode !== "disabled" &&
    config.providers.some(
      (provider) => provider.name === "casdoor" && provider.enabled
    );

  if (!available) return null;

  return (
    <Button
      block
      htmlType="button"
      className="!w-full"
      icon={<UserRoundPlus size={18} />}
      onClick={() => oauthService.startOAuthSignup("casdoor")}
    >
      {t("auth.casdoorSignup")}
    </Button>
  );
}

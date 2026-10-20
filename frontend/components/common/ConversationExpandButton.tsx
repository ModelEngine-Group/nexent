// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Button, Tooltip } from "antd";
import { PanelLeft } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useSidebar } from "@/components/ui/sidebar";

export function ConversationExpandButton() {
  const { toggleSidebar } = useSidebar();
  const { t } = useTranslation();
  return (
    <Tooltip title={t("chat.sidebar.expand")}>
      <Button
        type="text"
        aria-label={t("chat.sidebar.expand")}
        aria-expanded={false}
        className="!size-8 shrink-0 !rounded-[4px] !border-0 !bg-transparent !p-0 !text-[#777777] !shadow-none hover:!bg-[#f0f0f0] hover:!text-[#191919] focus-visible:!bg-[#f0f0f0]"
        onClick={toggleSidebar}
      >
        <PanelLeft className="size-4" aria-hidden />
      </Button>
    </Tooltip>
  );
}

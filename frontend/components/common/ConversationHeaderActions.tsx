// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { SquarePen } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useSidebar } from "@/components/ui/sidebar";
import { Button, Tooltip } from "antd";
import { ConversationExpandButton } from "./ConversationExpandButton";

interface ConversationHeaderActionsProps {
  position: "leading" | "trailing";
  onNewConversation: () => void | Promise<void>;
}

export function ConversationHeaderActions({
  position,
  onNewConversation,
}: ConversationHeaderActionsProps) {
  const { state, isMobile, openMobile } = useSidebar();
  const { t } = useTranslation();
  const collapsed = isMobile ? !openMobile : state === "collapsed";

  if (!collapsed) return null;

  return position === "leading" ? (
    <ConversationExpandButton />
  ) : (
    <Tooltip title={t("workbench.sidebar.newConversation")}>
      <Button
        type="text"
        aria-label={t("workbench.sidebar.newConversation")}
        className="size-8 shrink-0"
        onClick={onNewConversation}
      >
        <SquarePen className="size-4" aria-hidden />
      </Button>
    </Tooltip>
  );
}

// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useContext } from "react";
import { ActionBarMorePrimitive, useAui } from "@assistant-ui/react";
import { Share2Icon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { ConversationShareContext } from "./conversation-share-context";

export function ConversationShareMenuItem() {
  const share = useContext(ConversationShareContext);
  const aui = useAui();
  const { t } = useTranslation();
  if (!share) return null;
  return (
    <ActionBarMorePrimitive.Item
      disabled={share.disabled}
      onSelect={() => share.shareTurn(aui.message.getState().id)}
      className="flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm outline-none hover:bg-accent focus:bg-accent data-[disabled]:opacity-50"
    >
      <Share2Icon className="size-4" />
      {t("chatInterface.shareConversation")}
    </ActionBarMorePrimitive.Item>
  );
}

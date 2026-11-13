// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useContext } from "react";
import { ActionBarMorePrimitive, useAui } from "@assistant-ui/react";
import { GitBranchIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { ConversationBranchContext } from "./conversation-branch-context";

export function ConversationBranchMenuItem() {
  const branch = useContext(ConversationBranchContext);
  const aui = useAui();
  const { t } = useTranslation();
  if (!branch) return null;
  return (
    <ActionBarMorePrimitive.Item
      disabled={branch.disabled}
      onSelect={() => {
        const selected = aui.message.getState();
        branch.branchFromMessage(selected.id, selected.branchNumber);
      }}
      className="flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm outline-none hover:bg-accent focus:bg-accent data-[disabled]:opacity-50"
    >
      <GitBranchIcon className="size-4" />
      {t("chat.thread.branchToNewChat")}
    </ActionBarMorePrimitive.Item>
  );
}

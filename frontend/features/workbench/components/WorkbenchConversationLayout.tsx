// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { ConversationSidebarProvider } from "@/components/common/ConversationSidebarProvider";

interface WorkbenchConversationLayoutProps {
  ready: boolean;
  children: ReactNode;
}

export function WorkbenchConversationLayout({
  ready,
  children,
}: WorkbenchConversationLayoutProps) {
  const { t } = useTranslation();
  return (
    <ConversationSidebarProvider scope="workbench" className="w-full h-full">
      {ready ? (
        children
      ) : (
        <div className="flex h-full flex-1 items-center justify-center text-sm text-muted-foreground">
          {t("chat.threadList.loading")}
        </div>
      )}
    </ConversationSidebarProvider>
  );
}

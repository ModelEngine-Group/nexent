// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

interface ConversationLoadingBoundaryProps {
  loading: boolean;
  children: ReactNode;
}

/** Retains chat state while preventing interaction with a pending history. */
export function ConversationLoadingBoundary({
  loading,
  children,
}: ConversationLoadingBoundaryProps) {
  const { t } = useTranslation();
  return (
    <div className="relative min-h-0 flex-1" aria-busy={loading}>
      <div className={`h-full ${loading ? "invisible" : ""}`} inert={loading}>
        {children}
      </div>
      {loading && (
        <div
          role="status"
          className="absolute inset-0 flex items-center justify-center bg-background text-sm text-muted-foreground"
        >
          {t("chat.threadList.loading")}
        </div>
      )}
    </div>
  );
}

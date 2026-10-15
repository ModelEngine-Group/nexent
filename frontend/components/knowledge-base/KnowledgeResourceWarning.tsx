// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { AlertCircle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Tooltip } from "antd";

import type { KnowledgeResourceStatusEntry } from "@/types/knowledgeResource";

/**
 * Red exclamation marker attached to one knowledge base item.
 *
 * The marker is purely informational: the item stays selected, keeps its
 * remove button, and the reason is exposed to both mouse and keyboard users.
 * The icon is focusable so keyboard users can Tab onto it, the reason appears
 * on focus as well as hover, and the focus ring keeps it visible while focused.
 */
export default function KnowledgeResourceWarning({
  entry,
  className,
}: {
  entry: KnowledgeResourceStatusEntry;
  className?: string;
}) {
  const { t } = useTranslation("common");
  const reasonKey = `knowledgeResource.reason.${
    entry.reason_code || "KNOWLEDGE_UNAVAILABLE_OR_INACCESSIBLE"
  }`;
  const reason = t(reasonKey, {
    defaultValue: t(
      "knowledgeResource.reason.KNOWLEDGE_UNAVAILABLE_OR_INACCESSIBLE"
    ),
  });

  return (
    <Tooltip title={reason} trigger={["hover", "focus"]}>
      <AlertCircle
        role="img"
        tabIndex={0}
        aria-label={reason}
        data-testid="knowledge-resource-warning"
        className={`size-3.5 shrink-0 cursor-help rounded-sm text-red-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500 ${className ?? ""}`}
      />
    </Tooltip>
  );
}

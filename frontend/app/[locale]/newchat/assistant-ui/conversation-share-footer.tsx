// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Checkbox } from "antd";
import { LinkIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { StandardButton } from "@/components/common/StandardButton";

interface ConversationShareFooterProps {
  selectedCount: number;
  totalCount: number;
  creating: boolean;
  onToggleAll: () => void;
  onCancel: () => void;
  onCreate: () => void;
}

export function ConversationShareFooter({
  selectedCount,
  totalCount,
  creating,
  onToggleAll,
  onCancel,
  onCreate,
}: ConversationShareFooterProps) {
  const { t } = useTranslation();
  return (
    <footer
      role="region"
      className="shrink-0 border-t bg-background px-4 py-4"
      aria-label={t("chatInterface.shareConversation")}
    >
      <div className="mx-auto flex max-w-[890px] flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <Checkbox
            checked={totalCount > 0 && selectedCount === totalCount}
            indeterminate={selectedCount > 0 && selectedCount < totalCount}
            disabled={creating}
            onChange={onToggleAll}
          >
            {t("common.selectAll")}
          </Checkbox>
          <span className="text-muted-foreground">
            {t("chatInterface.selectedShareCount", { count: selectedCount })}
          </span>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <StandardButton disabled={creating} onClick={onCancel}>
            {t("common.cancel")}
          </StandardButton>
          <StandardButton
            variant="primary"
            icon={<LinkIcon className="size-4" />}
            loading={creating}
            disabled={!selectedCount || creating}
            onClick={onCreate}
          >
            {t("chatInterface.createPublicLink")}
          </StandardButton>
        </div>
      </div>
    </footer>
  );
}

// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useState } from "react";
import { Button, Empty, Popover, Spin } from "antd";
import { History, SquarePen } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { useCreatorHistories } from "@/hooks/chat/useCreatorHistories";

interface CreatorHistoryToolbarProps {
  history: ReturnType<typeof useCreatorHistories>;
  selectedId?: string;
  disabled: boolean;
  restoring: boolean;
  onSelect: (id: number) => Promise<void>;
  onNew: () => Promise<void>;
  resourceKind?: "agent" | "skill";
}

export function CreatorHistoryToolbar({
  history,
  selectedId,
  disabled,
  restoring,
  onSelect,
  onNew,
  resourceKind = "agent",
}: CreatorHistoryToolbarProps) {
  const { t } = useTranslation("common");
  const [open, setOpen] = useState(false);
  const title = t(
    resourceKind === "skill"
      ? "nl2skill.history.title"
      : "nl2agent.history.title"
  );
  const content = (
    <div className="w-72 max-w-[calc(100vw-32px)]">
      {history.failed ? (
        <div role="alert">
          {t("nl2agent.history.loadFailed")}
          <Button type="link" onClick={() => void history.refetch()}>
            {t("nl2agent.history.retry")}
          </Button>
        </div>
      ) : history.pending ? (
        <div className="flex justify-center p-4" role="status">
          <Spin size="small" />
        </div>
      ) : history.items.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t("nl2agent.history.empty")}
        />
      ) : (
        <ul className="max-h-72 overflow-y-auto" aria-label={title}>
          {history.items.map((item) => (
            <li key={item.conversation_id}>
              <Button
                type="text"
                block
                className="!h-auto !py-2 !text-left"
                disabled={disabled || restoring}
                aria-current={
                  selectedId === String(item.conversation_id)
                    ? "true"
                    : undefined
                }
                onClick={() => {
                  setOpen(false);
                  void onSelect(item.conversation_id);
                }}
              >
                <span className="flex w-full min-w-0 flex-col">
                  <span className="truncate">
                    {item.conversation_title || t("nl2agent.history.untitled")}
                  </span>
                  <span className="text-xs text-slate-400">
                    {new Date(
                      item.last_activity_time ??
                        item.update_time ??
                        item.create_time
                    ).toLocaleString()}
                  </span>
                </span>
              </Button>
            </li>
          ))}
          {history.hasMore && (
            <li>
              <Button
                type="link"
                block
                loading={history.fetchingMore}
                onClick={() => void history.loadMore()}
              >
                {t("nl2agent.history.more")}
              </Button>
            </li>
          )}
        </ul>
      )}
    </div>
  );
  return (
    <div className="flex shrink-0 items-center justify-end gap-2 px-4 pt-4 pb-2">
      {restoring && <Spin size="small" />}
      <Popover
        placement="bottomRight"
        trigger="click"
        open={open && !disabled && !restoring}
        onOpenChange={(value) => {
          setOpen(value);
          if (value) void history.refetch();
        }}
        title={title}
        content={content}
      >
        <Button
          type="text"
          size="small"
          icon={<History size={14} />}
          disabled={disabled || restoring}
        >
          {t("nl2agent.history.label")}{" "}
          {history.failed ? "—" : (history.total ?? "…")}
        </Button>
      </Popover>
      <Button
        type="text"
        size="small"
        icon={<SquarePen size={14} />}
        disabled={disabled || restoring}
        onClick={() => {
          setOpen(false);
          void onNew();
        }}
      >
        {t("nl2agent.history.new")}
      </Button>
    </div>
  );
}

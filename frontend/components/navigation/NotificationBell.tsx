// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Badge, Button, ConfigProvider, Dropdown, Tooltip } from "antd";
import { Bell } from "lucide-react";
import { useTranslation } from "react-i18next";

import { formatNotificationMessage } from "@/lib/notificationMessage";
import {
  buildRepositoryReviewDeepLink,
  isRepositoryReviewNotification,
} from "@/lib/notificationNavigation";
import { formatDateTime } from "@/lib/utils";
import type { NotificationItem } from "@/types/notification";
import { NavigationRailLabel } from "@/components/navigation/NavigationRailLabel";

interface NotificationBellProps {
  unreadCount: number;
  items: NotificationItem[];
  isLoading: boolean;
  rail?: boolean;
  expanded?: boolean;
  onOpenChange?: (open: boolean) => void;
  onMarkRead?: (receiverId: number) => Promise<void>;
  onMarkAllRead?: () => Promise<void>;
  isMarkingAllRead?: boolean;
}

export function NotificationBell({
  unreadCount,
  items,
  isLoading,
  rail = false,
  expanded = false,
  onOpenChange,
  onMarkRead,
  onMarkAllRead,
  isMarkingAllRead = false,
}: NotificationBellProps) {
  const { t } = useTranslation("common");
  const router = useRouter();
  const params = useParams<{ locale: string }>();
  const locale = params.locale || "en";
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const changeOpen = (open: boolean) => {
    setDropdownOpen(open);
    onOpenChange?.(open);
  };

  const tooltipTitle =
    unreadCount > 0
      ? t("notifications.bell.unread", { count: unreadCount })
      : t("notifications.bell.label");

  const handleItemClick = async (item: NotificationItem) => {
    if (!isRepositoryReviewNotification(item)) {
      return;
    }

    const deepLink = buildRepositoryReviewDeepLink(locale, item);
    if (!deepLink) {
      return;
    }

    changeOpen(false);
    if (onMarkRead) {
      await onMarkRead(item.receiver_id);
    }
    router.push(deepLink);
  };

  const panel = (
    <div className="w-[360px] max-w-[calc(100vw-2rem)] overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-900">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-700">
        <div className="text-sm font-semibold text-slate-900 dark:text-slate-100">
          {t("notifications.panel.title")}
        </div>
        <Button
          type="link"
          size="small"
          disabled={unreadCount === 0 || isMarkingAllRead}
          loading={isMarkingAllRead}
          className="h-auto px-0 text-xs"
          onClick={() => {
            if (onMarkAllRead) {
              void onMarkAllRead();
            }
          }}
        >
          {t("notifications.panel.markAllRead")}
        </Button>
      </div>
      <div className="max-h-[360px] overflow-y-auto">
        {isLoading ? (
          <div className="px-4 py-6 text-center text-sm text-slate-500 dark:text-slate-400">
            {t("common.loading")}...
          </div>
        ) : items.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm text-slate-500 dark:text-slate-400">
            {t("notifications.panel.empty")}
          </div>
        ) : (
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {items.map((item) => {
              const isClickable = isRepositoryReviewNotification(item);

              return (
                <li
                  key={item.receiver_id}
                  className={
                    isClickable
                      ? "flex cursor-pointer gap-3 bg-slate-50/80 px-4 py-3 transition-colors hover:bg-slate-100 dark:bg-slate-800/40 dark:hover:bg-slate-800/70"
                      : "flex gap-3 bg-slate-50/80 px-4 py-3 dark:bg-slate-800/40"
                  }
                  onClick={() => {
                    void handleItemClick(item);
                  }}
                  onKeyDown={(event) => {
                    if (!isClickable) {
                      return;
                    }
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      void handleItemClick(item);
                    }
                  }}
                  role={isClickable ? "button" : undefined}
                  tabIndex={isClickable ? 0 : undefined}
                >
                  <span
                    className="mt-2 h-2 w-2 flex-shrink-0 rounded-full bg-red-500"
                    aria-hidden="true"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm leading-5 text-slate-800 dark:text-slate-200">
                      {formatNotificationMessage(item, t)}
                    </p>
                    <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                      {formatDateTime(item.create_time)}
                    </p>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );

  const notificationControl = rail ? (
    <Button
      type="text"
      aria-label={t("notifications.bell.label")}
      className={`group !flex !h-11 !w-full cursor-pointer !justify-start !gap-0 overflow-hidden rounded-lg !p-0 !pr-2 !text-[var(--navigation-muted)] transition-colors duration-150 ease-out hover:!bg-[var(--navigation-hover)] hover:!text-[var(--navigation-foreground)] focus-visible:!text-[var(--navigation-foreground)] ${dropdownOpen ? "!bg-[var(--navigation-selected)] !text-[var(--navigation-foreground)]" : ""}`}
    >
      <span className="flex h-11 w-12 shrink-0 items-center justify-center">
        <Badge
          count={unreadCount}
          size="small"
          color="#ff4d4f"
          overflowCount={99}
          offset={[0, 0]}
          styles={{
            root: {
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              height: 20,
              width: 20,
              lineHeight: 1,
            },
          }}
        >
          <Bell className="h-5 w-5" />
        </Badge>
      </span>
      <NavigationRailLabel
        expanded={expanded}
        label={t("notifications.bell.label")}
        selected={dropdownOpen}
      />
    </Button>
  ) : (
    <Badge
      count={unreadCount}
      size="small"
      color="#ff4d4f"
      overflowCount={99}
      offset={[-2, 2]}
      styles={{
        root: {
          display: "inline-flex",
          alignItems: "center",
          height: 32,
          lineHeight: 1,
          verticalAlign: "middle",
        },
      }}
    >
      <Button
        type="text"
        size="small"
        aria-label={t("notifications.bell.label")}
        className="h-8 w-8 p-0 text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white"
        icon={<Bell className="h-4 w-4" />}
      />
    </Badge>
  );

  return (
    <ConfigProvider getPopupContainer={() => document.body}>
      <Dropdown
        trigger={["click"]}
        placement={rail ? "rightTop" : "bottomRight"}
        open={dropdownOpen}
        onOpenChange={changeOpen}
        getPopupContainer={() => document.body}
        popupRender={() => panel}
      >
        <Tooltip title={tooltipTitle}>{notificationControl}</Tooltip>
      </Dropdown>
    </ConfigProvider>
  );
}

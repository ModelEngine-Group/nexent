"use client";

import { Button, Tooltip } from "antd";
import { AvatarDropdown } from "@/components/auth/avatarDropdown";
import { useTranslation } from "react-i18next";
import { Activity, ChevronDown, Globe } from "lucide-react";
import { Dropdown } from "antd";
import Link from "next/link";
import { HEADER_CONFIG, SIDER_CONFIG } from "@/const/layoutConstants";
import { languageOptions } from "@/const/constants";
import { useLanguageSwitch } from "@/lib/language";
import React, { useEffect, useState } from "react";
import { Flex, Layout } from "antd";
import { ChatTopNavContent } from "./ChatTopNavContent";
import { NotificationBell } from "./NotificationBell";
import { useAuthorizationContext } from "../providers/AuthorizationProvider";
import { useDeployment } from "../providers/deploymentProvider";
import { monitoringService } from "@/services/monitoringService";
import { useMarkAllNotificationsRead, useMarkNotificationRead, useNotifications } from "@/hooks/useNotifications";
import type { MonitoringStatus } from "@/types/monitoring";
import { USER_ROLES } from "@/const/auth";

const { Header } = Layout;

function buildMonitoringUrl(status: MonitoringStatus | null): string | null {
  if (!status?.telemetry_enabled || typeof window === "undefined") return null;

  return status.dashboard_url || null;
}

export function TopNavbar({ isChatPage }: { isChatPage: boolean }) {
  const { t } = useTranslation("common");
  const { user, isLoading } = useAuthorizationContext();
  const { isSpeedMode } = useDeployment();
  const { currentLanguage, handleLanguageChange } = useLanguageSwitch();
  const [monitoringStatus, setMonitoringStatus] =
    useState<MonitoringStatus | null>(null);
  const canViewMonitoringDashboard =
    isSpeedMode || user?.role === USER_ROLES.SU;

  const showNotificationBell = !isSpeedMode && !!user;
  const {
    unreadCount,
    items,
    isLoading: isNotificationsLoading,
  } = useNotifications(showNotificationBell);
  const markNotificationReadMutation = useMarkNotificationRead();
  const markAllNotificationsReadMutation = useMarkAllNotificationsRead();

  useEffect(() => {
    if (!canViewMonitoringDashboard) {
      setMonitoringStatus(null);
      return;
    }

    let mounted = true;

    monitoringService.fetchStatus().then((status) => {
      if (mounted) {
        setMonitoringStatus(status);
      }
    });

    return () => {
      mounted = false;
    };
  }, [canViewMonitoringDashboard]);

  const monitoringUrl = canViewMonitoringDashboard
    ? buildMonitoringUrl(monitoringStatus)
    : null;

  const openMonitoringDashboard = () => {
    if (!monitoringUrl) return;
    window.open(monitoringUrl, "_blank", "noopener,noreferrer");
  };

  // Left content - Logo + optional additional title (aligned with sidebar width)
  const leftContent = (
    <Flex align="center">
      {/* Logo section - matches sidebar width */}
      <Link
        href="/"
        className="cursor-pointer hover:opacity-80 transition-opacity flex-shrink-0 "
        style={{ width: SIDER_CONFIG.EXPANDED_WIDTH - 17 }}
      >
        <Flex align="center" gap={8}>
          <img src="/modelengine-logo2.png" alt="ModelEngine" className="h-9" />
        </Flex>
      </Link>

      {/* Additional title with separator - outside of sidebar width */}
      {isChatPage && (
        <Flex align="center" gap={12}>
          <div className="h-6 border-l border-slate-300 dark:border-slate-600"></div>
          <div className="text-slate-600 dark:text-slate-400">
            <ChatTopNavContent />
          </div>
        </Flex>
      )}
    </Flex>
  );

  // Right content - Additional content + default navigation items
  const rightContent = (
    <Flex align="center" gap={16} className="hidden md:flex">
      {monitoringUrl && (
        <Tooltip title={t("monitoring.topbar.openDashboard")}>
          <Button
            type="text"
            size="small"
            aria-label={t("monitoring.topbar.openDashboard")}
            className="h-8 w-8 p-0 text-emerald-600 hover:text-emerald-700 dark:text-emerald-400 dark:hover:text-emerald-300"
            icon={<Activity className="h-4 w-4" />}
            onClick={openMonitoringDashboard}
          />
        </Tooltip>
      )}

      {/* Language switcher */}
      <Dropdown
        menu={{
          items: languageOptions.map((opt) => ({
            key: opt.value,
            label: opt.label,
          })),
          onClick: ({ key }) => handleLanguageChange(key as string),
        }}
      >
        <a className="ant-dropdown-link text-xs font-medium text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white transition-colors cursor-pointer w-[90px] border-0 shadow-none bg-transparent text-left no-underline">
          <Flex align="center" gap={6}>
            <Globe className="h-3.5 w-3.5" />
            {languageOptions.find((o) => o.value === currentLanguage)?.label ||
              currentLanguage}
            <ChevronDown size={12} />
          </Flex>
        </a>
      </Dropdown>

      {showNotificationBell && (
        <NotificationBell
          unreadCount={unreadCount}
          items={items}
          isLoading={isNotificationsLoading}
          isMarkingAllRead={markAllNotificationsReadMutation.isPending}
          onMarkRead={async (receiverId) => {
            await markNotificationReadMutation.mutateAsync(receiverId);
          }}
          onMarkAllRead={async () => {
            await markAllNotificationsReadMutation.mutateAsync();
          }}
        />
      )}

      {/* User status - only shown in full version */}
      {!isSpeedMode && (
        <Flex align="center" gap={8}>
          {isLoading ? (
            <span className="text-xs font-medium text-slate-600">
              {t("common.loading")}...
            </span>
          ) : user ? (
            <span className="text-xs font-medium text-slate-600 max-w-[150px] truncate">
              {user.email}
            </span>
          ) : null}
          <AvatarDropdown />
        </Flex>
      )}
    </Flex>
  );

  return (
    <Header
      className="w-full py-3 border-b border-slate-200 dark:border-slate-700 bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm fixed top-0 z-50"
      style={{ height: HEADER_CONFIG.DISPLAY_HEIGHT, background: "#ffffff", paddingInline: 16 }}
    >
      <div className="h-full flex items-center justify-between">
        {/* Left section - Logo + additional title */}
        {leftContent}

        {/* Right section - Additional content + default navigation */}
        {rightContent}
      </div>
    </Header>
  );
}

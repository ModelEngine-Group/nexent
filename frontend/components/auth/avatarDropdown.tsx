// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Dropdown, Avatar, Spin, Button, Tag, ConfigProvider } from "antd";
import {
  Activity,
  BookMarked,
  Check,
  ChevronRight,
  Copyright,
  ExternalLink,
  Globe,
  LogOut,
  LogIn,
  UserRound,
  UserRoundPlus,
} from "lucide-react";
import { GithubOutlined } from "@ant-design/icons";
import type { ItemType } from "antd/es/menu/interface";
import Link from "next/link";

import { useAuthenticationContext } from "@/components/providers/AuthenticationProvider";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { USER_ROLES } from "@/const/auth";
import { APP_VERSION, languageOptions } from "@/const/constants";
import { useAccountMonitoring } from "@/hooks/useAccountMonitoring";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import { useLanguageSwitch } from "@/lib/language";
import { useGlobalConfigStore } from "@/stores/global";
import { NavigationRailLabel } from "@/components/navigation/NavigationRailLabel";

interface AvatarDropdownProps {
  rail?: boolean;
  expanded?: boolean;
  onOpenChange?: (open: boolean) => void;
}

const MENU_POPUP_CLASS =
  "[&_.ant-dropdown-menu]:!flex [&_.ant-dropdown-menu]:!flex-col [&_.ant-dropdown-menu]:!gap-1 " +
  "[&_.ant-dropdown-menu]:!p-1 [&_.ant-dropdown-menu]:!rounded-[12px] [&_.ant-dropdown-menu]:!bg-white " +
  "[&_.ant-dropdown-menu]:!shadow-[0_8px_24px_rgba(0,0,0,0.16)] " +
  "[&_.ant-dropdown-menu]:!max-h-[calc(100dvh-16px)] [&_.ant-dropdown-menu]:!overflow-y-auto " +
  "[&_.ant-dropdown-menu-item:not(.account-menu-identity)]:!h-10 [&_.ant-dropdown-menu-item]:!rounded-lg [&_.ant-dropdown-menu-item]:!p-2 " +
  "[&_.ant-dropdown-menu-submenu-title]:!h-10 [&_.ant-dropdown-menu-submenu-title]:!rounded-lg [&_.ant-dropdown-menu-submenu-title]:!p-2 " +
  "[&_.ant-dropdown-menu-title-content]:!min-w-0 [&_.ant-dropdown-menu-title-content]:!text-base " +
  "[&_.ant-dropdown-menu-title-content]:!leading-6 [&_.ant-dropdown-menu-title-content]:!font-normal " +
  "[&_.ant-dropdown-menu-item-icon]:!me-2 [&_.ant-dropdown-menu-item-icon]:!text-[20px] " +
  "[&_.ant-dropdown-menu-item-divider]:!my-0 [&_.ant-dropdown-menu-item-divider]:!bg-[#f0f0f0] " +
  "[&_.ant-dropdown-menu-item:not(.account-menu-readonly):hover]:!bg-[rgba(25,25,25,0.08)] " +
  "[&_.ant-dropdown-menu-submenu-title:hover]:!bg-[rgba(25,25,25,0.08)] " +
  "[&_.ant-dropdown-menu]:!text-[#191919] [&_.ant-dropdown-menu]:!tracking-[0px]";

export function AvatarDropdown({
  rail = false,
  expanded = false,
  onOpenChange,
}: AvatarDropdownProps) {
  const { user } = useAuthorizationContext();
  const { isLoading, logout, openLoginModal, openRegisterModal } =
    useAuthenticationContext();
  const { appVersion } = useDeployment();
  const { config } = useGlobalConfigStore();
  const monitoringUrl = useAccountMonitoring();
  const { currentLanguage, handleLanguageChange } = useLanguageSwitch();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const changeOpen = (open: boolean) => {
    setDropdownOpen(open);
    onOpenChange?.(open);
  };
  const { t } = useTranslation("common");
  const { confirm } = useConfirmModal();

  const getRoleDisplayName = (role: string) => {
    switch (role) {
      case USER_ROLES.SPEED:
        return t("auth.speed");
      case USER_ROLES.SU:
        return t("auth.su");
      case USER_ROLES.ADMIN:
        return t("auth.admin");
      case USER_ROLES.DEV:
        return t("auth.dev");
      case USER_ROLES.ASSET_OWNER:
        return t("auth.assetOwner");
      default:
        return t("auth.user");
    }
  };

  if (isLoading) {
    return rail ? (
      <div className="flex h-12 w-12 items-center justify-center p-2">
        <Spin size="small" />
      </div>
    ) : (
      <Spin size="small" />
    );
  }

  const identity = user?.username?.trim() || user?.email?.trim() || "-";
  const profileLocale = currentLanguage.split("-")[0] === "en" ? "en" : "zh";
  const accountItems: ItemType[] = user
    ? [
        {
          key: "user-info",
          label: (
            <div className="flex h-[52px] min-w-0 flex-col justify-center gap-1">
              <div className="truncate" title={identity}>
                {identity}
              </div>
              <Tag className="!m-0 h-6 w-fit !border-0 !bg-[rgba(208,216,253,0.5)] !px-2 !text-xs !leading-6 !text-[#1f55b5]">
                {getRoleDisplayName(user.role)}
              </Tag>
            </div>
          ),
          className:
            "account-menu-identity account-menu-readonly !h-[68px] !cursor-default hover:!bg-transparent",
        },
        { type: "divider" },
        {
          key: "profile",
          icon: <UserRound size={20} />,
          label: (
            <Link href={`/${profileLocale}/users`} prefetch={false}>
              {t("profile.title")}
            </Link>
          ),
        },
      ]
    : [
        {
          key: "not-logged-in",
          label: t("auth.notLoggedIn"),
          className:
            "account-menu-readonly !cursor-default hover:!bg-transparent",
        },
        { type: "divider" },
        {
          key: "login",
          icon: <LogIn size={20} />,
          label: t("auth.login"),
          onClick: () => openLoginModal(),
        },
        {
          key: "register",
          icon: <UserRoundPlus size={20} />,
          label: t("auth.register"),
          onClick: () => openRegisterModal(),
        },
      ];

  const version = appVersion || APP_VERSION;
  const supplementalItems: ItemType[] = [
    {
      key: "language",
      icon: <Globe size={20} />,
      label: t("accountMenu.language"),
      expandIcon: <ChevronRight size={16} />,
      popupClassName: `${MENU_POPUP_CLASS} [&_.ant-dropdown-menu]:!w-[225px]`,
      children: languageOptions.map((option) => ({
        key: `language-${option.value}`,
        label: (
          <span className="flex items-center justify-between gap-2">
            <span>{option.label}</span>
            {currentLanguage.split("-")[0] === option.value && (
              <Check size={16} aria-label={t("accountMenu.selectedLanguage")} />
            )}
          </span>
        ),
        onClick: () => handleLanguageChange(option.value),
      })),
    },
    {
      key: "version",
      icon: <BookMarked size={20} />,
      label: (
        <span className="flex min-w-0 items-center justify-between gap-2">
          <span className="shrink-0">{t("accountMenu.version")}</span>
          <span className="truncate" title={version}>
            {version}
          </span>
        </span>
      ),
      className: "account-menu-readonly !cursor-default hover:!bg-transparent",
    },
    ...(monitoringUrl
      ? [
          {
            key: "monitoring",
            icon: <Activity size={20} />,
            label: (
              <a href={monitoringUrl} target="_blank" rel="noopener noreferrer">
                {t("monitoring.topbar.openDashboard")}
              </a>
            ),
          },
        ]
      : []),
    ...(config.aboutConfig === "open"
      ? [
          {
            key: "github",
            icon: <GithubOutlined />,
            label: (
              <a
                href="https://github.com/ModelEngine-Group/nexent"
                target="_blank"
                rel="noopener noreferrer"
              >
                {t("accountMenu.github")}
              </a>
            ),
          },
          {
            key: "modelengine",
            icon: <ExternalLink size={20} />,
            label: <a href="http://modelengine-ai.net">ModelEngine</a>,
          },
          {
            key: "terms",
            icon: <BookMarked size={20} />,
            label: (
              <a href="https://github.com/nexent-hub/nexent?tab=License-1-ov-file#readme">
                {t("page.termsOfUse")}
              </a>
            ),
          },
        ]
      : []),
    {
      key: "copyright",
      icon: <Copyright size={20} />,
      label: (
        <span className="block truncate">
          {t("page.copyright", { year: new Date().getFullYear() })}
        </span>
      ),
      className: "account-menu-readonly !cursor-default hover:!bg-transparent",
    },
  ];

  const menuItems: ItemType[] = [
    ...accountItems,
    ...supplementalItems,
    ...(user
      ? [
          { type: "divider" as const },
          {
            key: "logout",
            icon: <LogOut size={20} />,
            label: t("auth.logout"),
            onClick: () => {
              confirm({
                title: t("auth.confirmLogout"),
                content: t("auth.confirmLogoutPrompt"),
                onOk: () => {
                  logout();
                },
              });
            },
          },
        ]
      : []),
  ];

  return (
    <ConfigProvider getPopupContainer={() => document.body}>
      <Dropdown
        menu={{
          items: menuItems,
          onClick: ({ key }) => {
            if (
              !["user-info", "not-logged-in", "version", "copyright"].includes(
                key
              )
            )
              changeOpen(false);
          },
        }}
        placement={rail ? "topLeft" : "bottomRight"}
        trigger={["click"]}
        open={dropdownOpen}
        onOpenChange={(open, info) => {
          if (info.source === "trigger") changeOpen(open);
        }}
        classNames={{
          root: `${MENU_POPUP_CLASS} [&_.ant-dropdown-menu]:!w-[280px] [&_.ant-dropdown-menu]:!max-w-[calc(100vw-16px)]`,
        }}
        getPopupContainer={() => document.body}
      >
        {user ? (
          rail ? (
            <button
              type="button"
              aria-label={t("accountMenu.open")}
              className="flex h-11 w-full cursor-pointer items-center overflow-hidden rounded-lg border-0 bg-transparent p-0 pr-2 text-[#191919] hover:bg-[rgba(25,25,25,0.08)]"
            >
              <span className="flex h-11 w-12 shrink-0 items-center justify-center">
                <Avatar
                  src={user.avatarUrl}
                  size={20}
                  icon={<UserRound size={20} />}
                />
              </span>
              <NavigationRailLabel expanded={expanded} label={identity} />
            </button>
          ) : (
            <Button
              type="text"
              shape="circle"
              aria-label={t("accountMenu.open")}
              icon={
                <Avatar src={user.avatarUrl} icon={<UserRound size={18} />} />
              }
            />
          )
        ) : (
          <Button
            type="text"
            aria-label={t("accountMenu.open")}
            icon={rail ? undefined : <UserRound size={18} />}
            shape={rail ? undefined : "circle"}
            className={
              rail
                ? "!flex !h-11 !w-full !justify-start !gap-0 overflow-hidden rounded-lg !p-0 !pr-2 text-[#191919]"
                : undefined
            }
          >
            {rail && (
              <>
                <span className="flex h-11 w-12 shrink-0 items-center justify-center">
                  <UserRound size={20} />
                </span>
                <NavigationRailLabel
                  expanded={expanded}
                  label={t("auth.notLoggedIn")}
                />
              </>
            )}
          </Button>
        )}
      </Dropdown>
    </ConfigProvider>
  );
}

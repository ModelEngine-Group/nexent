// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Dropdown, Avatar, Spin, Button, Tag, ConfigProvider } from "antd";
import {
  Activity,
  Check,
  ChevronRight,
  ArrowUpRight,
  Globe,
  LogOut,
  LogIn,
  UserRound,
  UserRoundPlus,
} from "lucide-react";
import type { ItemType } from "antd/es/menu/interface";
import Link from "next/link";

import { useAuthenticationContext } from "@/components/providers/AuthenticationProvider";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { USER_ROLES } from "@/const/auth";
import { APP_VERSION, languageOptions } from "@/const/constants";
import { useUserDisplayName } from "@/hooks/auth/useUserDisplayName";
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
  "[&_.ant-dropdown-menu]:!flex [&_.ant-dropdown-menu]:!flex-col [&_.ant-dropdown-menu]:!gap-0 " +
  "[&_.ant-dropdown-menu]:!p-1.5 [&_.ant-dropdown-menu]:!rounded-lg [&_.ant-dropdown-menu]:!bg-white " +
  "[&_.ant-dropdown-menu]:!shadow-[0_4px_6px_-1px_rgb(0_0_0/0.1),0_2px_4px_-2px_rgb(0_0_0/0.1)] " +
  "[&_.ant-dropdown-menu]:!max-h-[calc(100dvh-16px)] [&_.ant-dropdown-menu]:!overflow-y-auto " +
  "[&_:where(.ant-dropdown-menu-item)]:!rounded-md [&_:where(.ant-dropdown-menu-item)]:!px-1.5 [&_:where(.ant-dropdown-menu-item)]:!py-1 " +
  "[&_.ant-dropdown-menu-item:not(.account-menu-identity):not(.account-menu-secondary)]:!h-7 " +
  "[&_.ant-dropdown-menu-submenu-title]:!flex [&_.ant-dropdown-menu-submenu-title]:!items-center [&_.ant-dropdown-menu-submenu-title]:!h-7 " +
  "[&_.ant-dropdown-menu-submenu-title]:!rounded-md [&_.ant-dropdown-menu-submenu-title]:!px-1.5 [&_.ant-dropdown-menu-submenu-title]:!py-1 " +
  "[&_.ant-dropdown-menu-title-content]:!min-w-0 " +
  "[&_.ant-dropdown-menu-item-icon]:!me-1.5 [&_.ant-dropdown-menu-item-icon]:!text-base [&_.ant-dropdown-menu-item-icon]:!w-4 [&_.ant-dropdown-menu-item-icon]:!h-4 [&_.ant-dropdown-menu-item-icon]:!shrink-0 " +
  "[&_.ant-dropdown-menu-item-divider]:!my-1 [&_.ant-dropdown-menu-item-divider]:!-mx-1 [&_.ant-dropdown-menu-item-divider]:!bg-[lab(90.6808%_-1.40554_-6.57337)] " +
  "[&_.ant-dropdown-menu-item:not(.account-menu-readonly):not(.account-menu-logout):hover]:!bg-[lab(94.1288%_-2.23359_-10.9012)] [&_.ant-dropdown-menu-submenu-title:hover]:!bg-[lab(94.1288%_-2.23359_-10.9012)] " +
  "[&_.ant-dropdown-menu-item:not(.account-menu-readonly):not(.account-menu-logout):focus-visible]:!bg-[lab(94.1288%_-2.23359_-10.9012)] [&_.ant-dropdown-menu-submenu-title:focus-visible]:!bg-[lab(94.1288%_-2.23359_-10.9012)] " +
  "[&_.account-menu-secondary:not(.account-menu-readonly):hover]:!text-[lab(11.6682%_-0.113927_-10.842)] " +
  "[&_.ant-dropdown-menu-item.account-menu-secondary:not(.account-menu-version)]:!h-6 [&_.account-menu-secondary]:!py-0.5 " +
  "[&_.account-menu-secondary:not(.account-menu-version)]:!text-[lab(47.7049%_-1.02875_-9.20491)] " +
  "[&_.account-menu-secondary_.ant-dropdown-menu-title-content]:!text-[11px] [&_.account-menu-secondary_.ant-dropdown-menu-title-content]:!leading-[16.5px] " +
  "[&_.ant-dropdown-menu-item.account-menu-version]:!h-[22.5px] [&_.account-menu-version]:!px-2 [&_.account-menu-version]:!pt-1 [&_.account-menu-version]:!pb-0.5 " +
  "[&_.account-menu-version]:!text-[color-mix(in_oklab,lab(47.7049%_-1.02875_-9.20491)_60%,transparent)] " +
  "[&_.account-menu-identity]:!px-2 [&_.account-menu-identity]:!pt-1.5 [&_.account-menu-identity]:!pb-2.5 " +
  "[&_.account-menu-secondary_a]:!text-inherit [&_.ant-dropdown-menu]:!text-[lab(11.6682%_-0.113927_-10.842)] [&_.ant-dropdown-menu]:!tracking-[0px]";

export function AvatarDropdown({
  rail = false,
  expanded = false,
  onOpenChange,
}: AvatarDropdownProps) {
  const { user } = useAuthorizationContext();
  const displayName = useUserDisplayName();
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

  const identity = displayName(
    user?.username,
    user?.username?.trim() || user?.email?.trim() || "-"
  );
  const profileLocale = currentLanguage.split("-")[0] === "en" ? "en" : "zh";
  const accountItems: ItemType[] = user
    ? [
        {
          key: "user-info",
          label: (
            <div className="flex h-11 min-w-0 items-center gap-3">
              <Avatar
                src={user.avatarUrl}
                size={36}
                icon={<UserRound size={18} />}
                className="shrink-0 !bg-[color-mix(in_oklab,lab(47.7049%_-1.02875_-9.20491)_15%,transparent)] !text-[lab(47.7049%_-1.02875_-9.20491)]"
              />
              <div className="flex h-11 min-w-0 flex-col gap-1">
                <div className="truncate" title={identity}>
                  {identity}
                </div>
                <Tag className="!m-0 !h-[15px] w-fit !border-0 !bg-[color-mix(in_oklab,lab(46.9268%_13.7028_-69.7937)_10%,transparent)] !px-1.5 !py-0.5 !text-[11px] !leading-[11px] !text-[lab(46.9268%_13.7028_-69.7937)]">
                  {getRoleDisplayName(user.role)}
                </Tag>
              </div>
            </div>
          ),
          className:
            "account-menu-identity account-menu-readonly !h-[60px] !cursor-default hover:!bg-transparent",
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
      label: (
        <span className="flex min-w-0 flex-1 items-center justify-between gap-2">
          <span>{t("accountMenu.language")}</span>
          <span className="text-xs leading-4 text-[lab(47.7049%_-1.02875_-9.20491)]">
            {
              languageOptions.find(
                (option) => option.value === currentLanguage.split("-")[0]
              )?.label
            }
          </span>
        </span>
      ),
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
    { type: "divider" },
    {
      key: "version",
      label: (
        <span className="flex min-w-0 flex-1 items-center justify-between gap-2">
          <span className="shrink-0">{t("accountMenu.about")}</span>
          <span className="truncate font-mono" title={version}>
            {version}
          </span>
        </span>
      ),
      className:
        "account-menu-secondary account-menu-version account-menu-readonly !cursor-default hover:!bg-transparent",
    },
    ...(monitoringUrl
      ? [
          {
            key: "monitoring",
            className: "account-menu-secondary",
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
            className: "account-menu-secondary",
            label: (
              <a
                href="https://github.com/ModelEngine-Group/nexent"
                target="_blank"
                rel="noopener noreferrer"
              >
                {t("accountMenu.github")}
                <ArrowUpRight
                  size={12}
                  className="ml-0.5 inline-block align-middle opacity-60"
                />
              </a>
            ),
          },
          {
            key: "modelengine",
            className: "account-menu-secondary",
            label: (
              <a href="http://modelengine-ai.net">
                ModelEngine
                <ArrowUpRight
                  size={12}
                  className="ml-0.5 inline-block align-middle opacity-60"
                />
              </a>
            ),
          },
          {
            key: "terms",
            className: "account-menu-secondary",
            label: (
              <a href="https://github.com/nexent-hub/nexent?tab=License-1-ov-file#readme">
                {t("page.termsOfUse")}
              </a>
            ),
          },
        ]
      : []),
  ];

  const menuItems: ItemType[] = [
    ...accountItems,
    ...supplementalItems,
    ...(user
      ? [
          { type: "divider" as const },
          {
            key: "logout",
            danger: true,
            className:
              "account-menu-logout !text-[lab(48.4493%_77.4328_61.5452)] hover:!bg-[color-mix(in_oklab,lab(48.4493%_77.4328_61.5452)_10%,transparent)]",
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
            if (!["user-info", "not-logged-in", "version"].includes(key))
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
          root: `${MENU_POPUP_CLASS} [&_.ant-dropdown-menu]:!w-[256px] [&_.ant-dropdown-menu]:!max-w-[calc(100vw-16px)]`,
        }}
        getPopupContainer={() => document.body}
      >
        {user ? (
          rail ? (
            <button
              type="button"
              aria-label={t("accountMenu.open")}
              className={`group flex h-11 w-full cursor-pointer items-center overflow-hidden rounded-lg border-0 bg-transparent p-0 pr-2 text-[var(--navigation-muted)] transition-colors duration-150 ease-out hover:bg-[var(--navigation-hover)] hover:text-[var(--navigation-foreground)] focus-visible:text-[var(--navigation-foreground)] ${dropdownOpen ? "!bg-[var(--navigation-selected)] !text-[var(--navigation-foreground)]" : ""}`}
            >
              <span className="flex h-11 w-12 shrink-0 items-center justify-center">
                <Avatar
                  src={user.avatarUrl}
                  size={20}
                  icon={<UserRound size={20} />}
                />
              </span>
              <NavigationRailLabel
                expanded={expanded}
                label={identity}
                selected={dropdownOpen}
              />
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
                ? `group !flex !h-11 !w-full !justify-start !gap-0 overflow-hidden rounded-lg !p-0 !pr-2 !text-[var(--navigation-muted)] transition-colors duration-150 ease-out hover:!bg-[var(--navigation-hover)] hover:!text-[var(--navigation-foreground)] focus-visible:!text-[var(--navigation-foreground)] ${dropdownOpen ? "!bg-[var(--navigation-selected)] !text-[var(--navigation-foreground)]" : ""}`
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
                  selected={dropdownOpen}
                />
              </>
            )}
          </Button>
        )}
      </Dropdown>
    </ConfigProvider>
  );
}

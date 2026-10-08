"use client";

import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { Dropdown, Avatar, Spin, Button, Tag, ConfigProvider } from "antd";
import {
  UserRound,
  LogOut,
  LogIn,
  UserRoundPlus,
  UserCircle,
} from "lucide-react";
import type { ItemType } from "antd/es/menu/interface";
import Link from "next/link";

import { useAuthenticationContext } from "@/components/providers/AuthenticationProvider";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import { getRoleColor } from "@/lib/auth";
import { USER_ROLES } from "@/const/auth";

interface AvatarDropdownProps {
  rail?: boolean;
}

export function AvatarDropdown({ rail = false }: AvatarDropdownProps) {
  const { user } = useAuthorizationContext();
  const { isLoading, logout, openLoginModal, openRegisterModal } =
    useAuthenticationContext();
  const [dropdownOpen, setDropdownOpen] = useState(false);
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
      case USER_ROLES.USER:
        return t("auth.user");
      case USER_ROLES.ASSET_OWNER:
        return t("auth.assetOwner");
      default:
        return t("auth.user");
    }
  };

  // Show loading while authentication is in progress
  if (isLoading) {
    return rail ? (
      <div className="flex h-12 w-12 items-center justify-center p-2">
        <Spin size="small" />
      </div>
    ) : (
      <Spin size="small" />
    );
  }
  if (!user) {
    const items: ItemType[] = [
      {
        key: "not-logged-in",
        label: (
          <div className="py-1">
            <div className="font-medium text-gray-500">
              {t("auth.notLoggedIn")}
            </div>
          </div>
        ),
        className: "cursor-default hover:bg-transparent",
        style: {
          backgroundColor: "transparent",
          cursor: "default",
        },
      },
      {
        type: "divider",
      },
      {
        key: "login",
        icon: <LogIn size={16} />,
        label: t("auth.login"),
        onClick: () => {
          setDropdownOpen(false);
          openLoginModal();
        },
      },
      {
        key: "register",
        icon: <UserRoundPlus size={16} />,
        label: t("auth.register"),
        onClick: () => {
          setDropdownOpen(false);
          openRegisterModal();
        },
      },
    ];

    return (
      <ConfigProvider getPopupContainer={() => document.body}>
        <Dropdown
          menu={{ items }}
          placement="bottomRight"
          arrow
          trigger={["click"]}
          open={dropdownOpen}
          onOpenChange={setDropdownOpen}
          popupRender={(menu: React.ReactNode) => (
            <div style={{ minWidth: "120px" }}>{menu}</div>
          )}
          getPopupContainer={() => document.body}
        >
          <Button
            type="text"
            icon={<UserRound size={rail ? 20 : 18} />}
            shape={rail ? undefined : "circle"}
            className={
              rail ? "h-12 w-12 rounded-[4px] p-2 text-[#191919]" : undefined
            }
          />
        </Dropdown>
      </ConfigProvider>
    );
  }

  const menuItems: ItemType[] = [
    {
      key: "user-info",
      label: (
        <div className="py-1">
          <div className="font-medium">
            {user.username?.trim() || user.email?.trim() || "-"}
          </div>
          <div className="mt-1">
            <Tag color={getRoleColor(user.role)}>
              {getRoleDisplayName(user.role)}
            </Tag>
          </div>
        </div>
      ),
      className: "cursor-default hover:bg-transparent",
      style: {
        backgroundColor: "transparent",
        cursor: "default",
      },
    },
    {
      type: "divider",
    },
    {
      key: "profile",
      icon: <UserCircle size={16} />,
      label: <Link href="/users">{t("sidebar.userManagement")}</Link>,
      onClick: () => {
        setDropdownOpen(false);
      },
    },
    {
      type: "divider",
    },
    {
      key: "logout",
      icon: <LogOut size={16} />,
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
  ];

  return (
    <ConfigProvider getPopupContainer={() => document.body}>
      <Dropdown
        menu={{ items: menuItems }}
        placement="bottomRight"
        arrow
        trigger={["click"]}
        getPopupContainer={() => document.body}
        popupRender={(menu: React.ReactNode) => (
          <div style={{ minWidth: "180px" }}>{menu}</div>
        )}
      >
        {rail ? (
          <button
            type="button"
            className="flex h-12 w-12 items-center justify-center rounded-[4px] border-0 bg-transparent p-2 text-[#191919]"
          >
            <Avatar
              src={user.avatarUrl}
              size={20}
              icon={<UserRound size={20} />}
            />
          </button>
        ) : (
          <Avatar
            src={user.avatarUrl}
            className="cursor-pointer"
            size="default"
            icon={<UserRound size={18} />}
          />
        )}
      </Dropdown>
    </ConfigProvider>
  );
}

"use client";

import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { Dropdown, Avatar, Spin, Button, Tag, ConfigProvider } from "antd";
import { UserRound, LogOut, LogIn, UserRoundPlus, UserCircle, Power } from "lucide-react";
import type { ItemType } from "antd/es/menu/interface";
import Link from "next/link";
import { App } from "antd";

import { useAuthenticationContext } from "@/components/providers/AuthenticationProvider";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import { getRoleColor } from "@/lib/auth";
import { USER_ROLES } from "@/const/auth";

export function AvatarDropdown() {
  const { user, isAuthzReady } = useAuthorizationContext();
  const { isLoading, logout, revoke, openLoginModal, openRegisterModal } =
    useAuthenticationContext();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const { t } = useTranslation("common");
  const { modal } = App.useApp();
  const { confirm } = useConfirmModal();

  // Show loading while authentication is in progress
  if (isLoading) {
    return <Spin size="small" />;
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
          <Button type="text" icon={<UserRound size={18} />} shape="circle" />
        </Dropdown>
      </ConfigProvider>
    );
  }

  // User has logged in, show user menu
  const menuItems: ItemType[] = [
    {
      key: "user-info",
      label: (
        <div className="py-1">
          <div className="font-medium">{user.email}</div>
          <div className="mt-1">
            <Tag color={getRoleColor(user.role)}>
              {t(`auth.${(user.role).toLowerCase()}`)}
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
    {
      key: "revoke",
      icon: <Power size={16} />,
      label: t("auth.revoke"),
      // danger: true,
      className: "hover:!bg-red-100 focus:!bg-red-400 focus:!text-white",
      onClick: () => {
        if (user.role === USER_ROLES.ADMIN) {
          modal.error({
            title: t("auth.refuseRevoke"),
            content: t("auth.refuseRevokePrompt"),
            okText: t("auth.confirm"),
          });
        } else {
          confirm({
            title: t("auth.confirmRevoke"),
            content: t("auth.confirmRevokePrompt"),
            okText: t("auth.confirmRevokeOk"),
            onOk: () => {
              revoke();
            },
          });
        }
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
        <Avatar
          src={user.avatarUrl}
          className="cursor-pointer"
          size="default"
          icon={<UserRound size={18} />}
        />
      </Dropdown>
    </ConfigProvider>
  );
}

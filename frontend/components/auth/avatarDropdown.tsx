"use client";

import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { Dropdown, Avatar, Spin, Button, Tag, ConfigProvider, App } from "antd";
import {
  UserOutlined,
  LogoutOutlined,
  LoginOutlined,
  PoweroffOutlined,
  CloseCircleFilled,
  UserAddOutlined,
} from "@ant-design/icons";
import type { ItemType } from "antd/es/menu/interface";

import { useAuth } from "@/hooks/useAuth";
import { getRoleColor } from "@/lib/auth";

export function AvatarDropdown() {
  const { user, isLoading, logout, revoke, openLoginModal, openRegisterModal } =
    useAuth();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const { t } = useTranslation("common");
  const { modal } = App.useApp();

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
        icon: <LoginOutlined />,
        label: t("auth.login"),
        onClick: () => {
          setDropdownOpen(false);
          openLoginModal();
        },
      },
      {
        key: "register",
        icon: <UserAddOutlined />,
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
          dropdownRender={(menu: React.ReactNode) => (
            <div style={{ minWidth: "120px" }}>{menu}</div>
          )}
          getPopupContainer={() => document.body}
        >
          <Button type="text" icon={<UserOutlined />} shape="circle" />
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
              {t(user.role === "admin" ? "auth.admin" : "auth.user")}
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
      key: "logout",
      icon: <LogoutOutlined />,
      label: t("auth.logout"),
      onClick: () => {
        modal.confirm({
          title: t("auth.confirmLogout"),
          content: t("auth.confirmLogoutPrompt"),
          okText: t("auth.confirm"),
          cancelText: t("auth.cancel"),
          onOk: () => {
            logout();
          },
        });
      },
    },
    {
      key: "revoke",
      icon: <PoweroffOutlined />,
      label: t("auth.revoke"),
      // danger: true,
      className:
        "hover:!bg-red-100 focus:!bg-red-400 focus:!text-white",
      onClick: () => {
        if (user.role === "admin") {
          modal.error({
            title: t("auth.refuseRevoke"),
            content: t("auth.refuseRevokePrompt"),
            okText: t("auth.confirm"),
          });
        } else {
          modal.confirm({
            title: t("auth.confirmRevoke"),
            content: t("auth.confirmRevokePrompt"),
            icon: <CloseCircleFilled style={{ color: "red" }} />,
            okText: t("auth.confirmRevokeOk"),
            cancelText: t("auth.cancel"),
            okButtonProps: { danger: true },
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
        dropdownRender={(menu: React.ReactNode) => (
          <div style={{ minWidth: "180px" }}>{menu}</div>
        )}
      >
        <Avatar
          src={user.avatar_url}
          className="cursor-pointer"
          size="default"
          icon={<UserOutlined />}
        />
      </Dropdown>
    </ConfigProvider>
  );
}

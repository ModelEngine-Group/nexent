"use client";

import { useTranslation } from "react-i18next";
import { Modal, Button } from "antd";
import { GithubOutlined } from "@ant-design/icons";
import { ExclamationCircleOutlined } from "@ant-design/icons";
import { UserPlus, LogIn } from "lucide-react";
import Image from "next/image";

import { useAuthenticationContext } from "@/components/providers/AuthenticationProvider";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";

/**
 * Authentication dialogs component
 * Contains login prompt, permission denied, and session expired modals
 */
export function AuthDialogs() {
  const { t } = useTranslation("common");

  const {
    isAuthPromptModalOpen,
    isSessionExpiredModalOpen,
    closeSessionExpiredModal,
    closeAuthPromptModal,
    openLoginModal,
    openRegisterModal,
  } = useAuthenticationContext();

  const {
    isAuthzPromptModalOpen,
    closeAuthzPromptModal,
  } = useAuthorizationContext();

  return (
    <>
      {/* Login prompt dialog - shown when user is not authenticated */}
      <Modal
        open={isAuthPromptModalOpen}
        onCancel={closeAuthPromptModal}
        footer={null}
        centered
        closable
        width={480}
        maskClosable={false}
      >
        <div className="relative bg-white p-4 rounded-2xl">
          {/* Logo */}
          <div className="flex justify-center mb-6">
            <Image
              src="/modelengine-logo.png"
              alt="ModelEngine Logo"
              width={80}
              height={80}
              className="object-contain"
            />
          </div>

          {/* Title */}
          <h2 className="text-3xl font-bold text-center mb-2 text-gray-900">
            {t("page.loginPrompt.title")}
          </h2>

          {/* Subtitle */}
          <p className="text-center text-gray-500 mb-8 mt-4 ml-10 mr-10 text-sm">
            {t(
              "A powerful AI agent platform for intelligent conversations and automation"
            )}
          </p>

          {/* Action buttons */}
          <div className="flex flex-col gap-3 mb-6">
            {/* Login button */}
            <Button
              onClick={() => {
                closeAuthPromptModal();
                openLoginModal();
              }}
              className="w-full h-12 rounded-lg font-medium flex items-center justify-center gap-2 shadow-sm"
              size="large"
              type="primary"
            >
              <LogIn className="h-5 w-5" />
              {t("page.loginPrompt.login")}
            </Button>

            {/* Register button */}
            <Button
              onClick={() => {
                closeAuthPromptModal();
                openRegisterModal();
              }}
              type="default"
              className="w-full h-12 border border-gray-300 rounded-lg font-medium flex items-center justify-center gap-2"
              size="large"
            >
              <UserPlus className="h-5 w-5" />
              {t("page.loginPrompt.register")}
            </Button>
          </div>

          {/* GitHub support */}
          <div className="flex items-center justify-center gap-2 text-gray-500 text-sm">
            <GithubOutlined className="text-base" />
            <a
              href="https://github.com/ModelEngine-Group/nexent"
              target="_blank"
              rel="noopener noreferrer"
            >
              {t("page.loginPrompt.githubSupport")}
            </a>
            <span></span>
          </div>
        </div>
      </Modal>

      {/* Permission denied dialog - shown when user is not authorized */}
      <Modal
        title={t("page.permissionDenied.title")}
        open={isAuthzPromptModalOpen}
        onCancel={closeAuthzPromptModal}
        footer={[
          <Button key="confirm" onClick={closeAuthzPromptModal} type="primary">
            {t("common.confirm")}
          </Button>,
        ]}
        centered
        closable={false}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <ExclamationCircleOutlined
            style={{ color: "#faad14", fontSize: "20px" }}
          />
          <span>{t("page.permissionDenied.content")}</span>
        </div>
      </Modal>

      {/* Session expired dialog - shown when user session has expired */}
      <Modal
        title={t("login.expired.title")}
        open={isSessionExpiredModalOpen}
        onOk={() => {
          closeSessionExpiredModal();
          openLoginModal();
        }}
        onCancel={closeSessionExpiredModal}
        okText={t("login.expired.okText")}
        cancelText={t("login.expired.cancelText")}
        centered
        closable={false}
        okButtonProps={{ type: "primary" }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <ExclamationCircleOutlined
            style={{ color: "#faad14", fontSize: "20px" }}
          />
          <span>{t("login.expired.content")}</span>
        </div>
      </Modal>
    </>
  );
}

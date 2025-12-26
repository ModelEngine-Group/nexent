"use client";

import { Button } from "@/components/ui/button";
import { AvatarDropdown } from "@/components/auth/avatarDropdown";
import { useTranslation } from "react-i18next";
import { useAuth } from "@/hooks/useAuth";
import { ChevronDown, Globe, Settings } from "lucide-react";
import { Dropdown, Modal, Input, message } from "antd";
import { configService } from "@/services/configService";
import { configStore } from "@/lib/config";
import Link from "next/link";
import { HEADER_CONFIG, SIDER_CONFIG } from "@/const/layoutConstants";
import { languageOptions } from "@/const/constants";
import { useLanguageSwitch } from "@/lib/language";
import React from "react";
import { Flex, Layout } from 'antd';
import {API_ENDPOINTS} from "@/services/api";
import {getAuthHeaders} from "@/lib/auth";
import log from "@/lib/logger";
const { Header } = Layout;

interface TopNavbarProps {
  /** Additional title text to display after logo (separated by |) */
  additionalTitle?: React.ReactNode;
  /** Additional content to insert before default right nav items */
  additionalRightContent?: React.ReactNode;
}

/**
 * Top navigation bar component
 * Displays logo, language switcher, and user authentication status
 * Can be customized with additionalTitle and additionalRightContent props
 */
export function TopNavbar({ additionalTitle, additionalRightContent }: TopNavbarProps) {
  const { t } = useTranslation("common");
  const { user, isLoading: userLoading, isSpeedMode } = useAuth();
  const { currentLanguage, handleLanguageChange } = useLanguageSwitch();
  const [isSetupModalVisible, setIsSetupModalVisible] = React.useState(false);
  const [meApiKey, setMeApiKey] = React.useState("");
  const openSetupModal = async () => {
    try{
      const response = await fetch(API_ENDPOINTS.config.load, {
          method: 'GET',
          headers: getAuthHeaders(),
        });
      if (!response.ok) {
        const errorData = await response.json();
        log.error('Failed to load configuration:', errorData);
        return false;
      }
      const result = await response.json();
      const config = result.config;
        setMeApiKey(config.modelengine.apiKey || "");
    } catch (e) {
      setMeApiKey("");
    }
    setIsSetupModalVisible(true);
  };

  const handleSaveMeConfig = async () => {
    try {
      // keep local embedding.apiConfig.apiKey in sync before saving
      configStore.updateModelConfig({
        embedding: {
          ...(configStore.getConfig().models?.embedding || {}),
          apiConfig: {
            ...(configStore.getConfig().models?.embedding?.apiConfig || {}),
            apiKey: meApiKey || "",
          },
        },
      } as any);

      const currentConfig = configStore.getConfig();
      const payload = {
        ...currentConfig,
        modelengine: { apiKey: meApiKey || "" },
      } as any;

      // POST the full config to backend and expect the backend to return the saved config structure
      const response = await fetch(API_ENDPOINTS.config.save, {
        method: "POST",
        headers: {
          ...getAuthHeaders(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => null);
        log.error("Failed to save configuration:", errData || response.statusText);
        message.error(t("common.retryLater"));
        return;
      }

      const result = await response.json();
      const returnedConfig = result?.config;

      if (returnedConfig) {
        // Update stores with returned config structure so the API key and other fields match backend
        try {
          configStore.updateConfig(returnedConfig);
          // ensure model embedding apiConfig is also updated (preserve existing shape)
          configStore.updateModelConfig({
            embedding: {
              ...(returnedConfig.models?.embedding || {}),
              apiConfig: {
                ...(returnedConfig.models?.embedding?.apiConfig || {}),
                apiKey: returnedConfig.modelengine?.apiKey || meApiKey || "",
              },
            },
          } as any);
        } catch (e) {
          // ignore update errors
        }

        // Update local state and notify listeners
        setMeApiKey(returnedConfig.modelengine?.apiKey || "");
        window.dispatchEvent(new CustomEvent("configChanged", { detail: { config: configStore.getConfig() } }));
        window.dispatchEvent(new CustomEvent("modelengineApiSaved", { detail: { apiKey: returnedConfig.modelengine?.apiKey || meApiKey || "" } }));
        message.success(t("common.button.save") || t("common.save"));
      } else {
        message.error(t("common.retryLater"));
      }
    } catch (e) {
      log.error("Exception saving configuration:", e);
      message.error(t("common.retryLater"));
    } finally {
      setIsSetupModalVisible(false);
    }
  };

  // Left content - Logo + optional additional title (aligned with sidebar width)
  const leftContent = (
    <Flex align="center">
      {/* Logo section - matches sidebar width */}
      <Link
        href="/"
        className="cursor-pointer hover:opacity-80 transition-opacity flex-shrink-0 "
        style={{ width: SIDER_CONFIG.EXPANDED_WIDTH-17 }}
      >
        <Flex align="center" gap={8}>
          <img
            src="/modelengine-logo2.png"
            alt="ModelEngine"
            className="h-7"
          />
          <span
            className="text-blue-600 dark:text-blue-500 font-bold"
            style={{
              fontSize: '20px',
              lineHeight: '24px',
              height: '22px',
            }}
          >
            {t("assistant.name")}
          </span>
        </Flex>
      </Link>

      {/* Additional title with separator - outside of sidebar width */}
      {additionalTitle && (
        <Flex align="center" gap={12}>
          <div className="h-6 border-l border-slate-300 dark:border-slate-600"></div>
          <div className="text-slate-600 dark:text-slate-400">
            {additionalTitle}
          </div>
        </Flex>
      )}
    </Flex>
  );

  // Right content - Additional content + default navigation items
  const rightContent = (
    <Flex align="center" gap={16} className="hidden md:flex">
      {/* Additional right content (e.g., status badge) */}
      {additionalRightContent}

      {/* ModelEngine config modal trigger (matches GitHub link style and is i18n) */}
      <Button
        variant="ghost"
        size="sm"
        onClick={openSetupModal}
        className="text-xs font-medium text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white transition-colors"
      >
        <Flex align="center" gap={4}>
          <Settings className="h-3.5 w-3.5" />
          {t("common.button.editConfig") || "ModelEngine 配置"}
        </Flex>
      </Button>

      {/* GitHub link */}
      <Link
        href="https://github.com/ModelEngine-Group/nexent"
        target="_blank"
        rel="noopener noreferrer"
        className="text-xs font-medium text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white transition-colors"
      >
        <Flex align="center" gap={4}>
          <svg
            height="16"
            width="16"
            viewBox="0 0 16 16"
            fill="currentColor"
            aria-hidden="true"
          >
            <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.65 7.65 0 0 1 2-.27c.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.19 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8z"></path>
          </svg>
          Github
        </Flex>
      </Link>


      {/* ModelEngine link */}
      <Link
        href="http://modelengine-ai.net"
        className="text-xs font-medium text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white transition-colors"
      >
        ModelEngine
      </Link>

      {/* Setup modal (inline, match existing SetupLayout modal style) */}
      <Modal
        title={t("common.button.editConfig")}
        open={isSetupModalVisible}
        onCancel={() => setIsSetupModalVisible(false)}
        onOk={handleSaveMeConfig}
        okText={t("common.button.save") || t("common.save")}
        cancelText={t("common.cancel")}
        destroyOnClose
        width={680}
      >
        <div className="space-y-3">
          <label className="block mb-1 text-sm font-medium text-gray-700">
            {t("model.dialog.label.apiKey")}
          </label>
          <Input.Password
            value={meApiKey}
            onChange={(e) => setMeApiKey(e.target.value)}
            placeholder={t("model.dialog.placeholder.apiKey")}
            autoComplete="new-password"
          />
        </div>
      </Modal>

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
        <a className="ant-dropdown-link text-xs font-medium text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white transition-colors cursor-pointer border-0 shadow-none bg-transparent text-left whitespace-nowrap">
          <Flex align="center" gap={4}>
            <Globe className="h-3.5 w-3.5" />
            {languageOptions.find((o) => o.value === currentLanguage)?.label ||
              currentLanguage}
            <ChevronDown size={12} />
          </Flex>
        </a>
      </Dropdown>

      {/* User status - only shown in full version */}
      {!isSpeedMode && (
        <Flex align="center" gap={8}>
          {userLoading ? (
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
      className="w-full py-3 px-4 border-b border-slate-200 dark:border-slate-700 bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm fixed top-0 z-50"
      style={{ height: HEADER_CONFIG.DISPLAY_HEIGHT }}
    >
      <Flex align="center" justify="space-between" className="h-full">
        {/* Left section - Logo + additional title */}
        {leftContent}

        {/* Right section - Additional content + default navigation */}
        {rightContent}

        {/* Mobile hamburger menu button */}
        <Button variant="ghost" size="icon" className="md:hidden">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="h-5 w-5"
          >
            <line x1="4" x2="20" y1="12" y2="12" />
            <line x1="4" x2="20" y1="6" y2="6" />
            <line x1="4" x2="20" y1="18" y2="18" />
          </svg>
        </Button>
      </Flex>
    </Header>
  );
}


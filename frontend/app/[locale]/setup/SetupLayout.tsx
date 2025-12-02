"use client";

import React, {ReactNode} from "react";
import {useTranslation} from "react-i18next";

import {Badge, Button, Dropdown} from "antd";
import {DownOutlined} from "@ant-design/icons";
import {FiRefreshCw} from "react-icons/fi";
import {Globe} from "lucide-react";
import {languageOptions} from "@/const/constants";
import {useLanguageSwitch} from "@/lib/language";
import {CONNECTION_STATUS, ConnectionStatus,} from "@/const/modelConfig";

// ================ Setup Header Content Components ================
// These components are exported so they can be used to customize the TopNavbar

interface SetupHeaderRightContentProps {
  connectionStatus: ConnectionStatus;
  isCheckingConnection: boolean;
  onCheckConnection: () => void;
}

export function SetupHeaderRightContent({
  connectionStatus,
  isCheckingConnection,
  onCheckConnection,
}: SetupHeaderRightContentProps) {
  const { t } = useTranslation();
  const { currentLanguage, handleLanguageChange } = useLanguageSwitch();

  // Get status text
  const getStatusText = () => {
    switch (connectionStatus) {
      case CONNECTION_STATUS.SUCCESS:
        return t("setup.header.status.connected");
      case CONNECTION_STATUS.ERROR:
        return t("setup.header.status.disconnected");
      case CONNECTION_STATUS.PROCESSING:
        return t("setup.header.status.checking");
      default:
        return t("setup.header.status.unknown");
    }
  };

  return (
      <div className="flex items-center gap-3">
        <Dropdown
          menu={{
            items: languageOptions.map((opt) => ({
              key: opt.value,
              label: opt.label,
            })),
            onClick: ({ key }) => handleLanguageChange(key as string),
          }}
        >
          <a className="ant-dropdown-link text-sm !font-medium text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white transition-colors flex items-center gap-2 cursor-pointer w-[110px] border-0 shadow-none bg-transparent text-left">
            <Globe className="h-4 w-4" />
            {languageOptions.find((o) => o.value === currentLanguage)?.label ||
              currentLanguage}
            <DownOutlined className="text-[10px]" />
          </a>
        </Dropdown>
        {/* ModelEngine connectivity status */}
        <div className="flex items-center px-3 py-1.5 rounded-md border border-slate-200 dark:border-slate-700">
          <Badge
            status={connectionStatus}
            text={getStatusText()}
            className="[&>.ant-badge-status-dot]:w-[8px] [&>.ant-badge-status-dot]:h-[8px] [&>.ant-badge-status-text]:text-base [&>.ant-badge-status-text]:ml-2 [&>.ant-badge-status-text]:font-medium"
          />
          <Button
            icon={
              <FiRefreshCw
                className={isCheckingConnection ? "animate-spin" : ""}
              />
            }
            size="small"
            type="text"
            onClick={onCheckConnection}
            disabled={isCheckingConnection}
            className="ml-2"
          />
        </div>
      </div>
  );
}

// ================ Navigation ================
interface NavigationProps {
  onBack?: () => void;
  onNext?: () => void;
  onComplete?: () => void;
  isSaving?: boolean;
  showBack?: boolean;
  showNext?: boolean;
  showComplete?: boolean;
  nextText?: string;
  completeText?: string;
}

function Navigation({
  onBack,
  onNext,
  onComplete,
  isSaving = false,
  showBack = false,
  showNext = false,
  showComplete = false,
  nextText,
  completeText,
}: NavigationProps) {
  const { t } = useTranslation();

  const handleClick = () => {
    if (showComplete && onComplete) {
      onComplete();
    } else if (showNext && onNext) {
      onNext();
    }
  };

  const buttonText = () => {
    if (showComplete) {
      return isSaving
        ? t("setup.navigation.button.saving")
        : completeText || t("setup.navigation.button.complete");
    }
    if (showNext) {
      return nextText || t("setup.navigation.button.next");
    }
    return "";
  };

  return (
    <div className="mt-3 flex justify-between" style={{ padding: "0 16px" }}> 
      <div className="flex gap-2">
        {showBack && onBack && (
          <button
            onClick={onBack}
            className="px-6 py-2.5 rounded-md flex items-center text-sm font-medium bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 cursor-pointer transition-colors"
          >
            {t("setup.navigation.button.previous")}
          </button>
        )}
      </div>

      <div className="flex gap-2">
        {(showNext || showComplete) && (
          <button
            onClick={handleClick}
            disabled={isSaving}
            className="px-6 py-2.5 rounded-md flex items-center text-sm font-medium bg-blue-600 dark:bg-blue-600 text-white hover:bg-blue-700 dark:hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            style={{
              border: "none",
              marginLeft: !showBack ? "auto" : undefined,
            }}
          >
            {buttonText()}
          </button>
        )}
      </div>
    </div>
  );
}

// ================ Layout ================
interface SetupLayoutProps {
  children: ReactNode;
  onBack?: () => void;
  onNext?: () => void;
  onComplete?: () => void;
  isSaving?: boolean;
  showBack?: boolean;
  showNext?: boolean;
  showComplete?: boolean;
  nextText?: string;
  completeText?: string;
}

/**
 * SetupLayout - Content wrapper for setup pages
 * This component should be wrapped by NavigationLayout
 * Use SetupHeaderRightContent for customizing the top navbar
 */
export default function SetupLayout({
  children,
  onBack,
  onNext,
  onComplete,
  isSaving = false,
  showBack = false,
  showNext = false,
  showComplete = false,
  nextText,
  completeText,
}: SetupLayoutProps) {
  return (
    <div className="w-full h-full bg-slate-50 dark:bg-slate-900 font-sans overflow-hidden">
      {/* Main content with fixed size */}
      <div className="max-w-[1800px] mx-auto px-8 pb-6 pt-6 bg-transparent h-full flex flex-col">
        <div className="flex-1 w-full h-full flex items-center justify-center">
        {children}
        </div>
        <Navigation
          onBack={onBack}
          onNext={onNext}
          onComplete={onComplete}
          isSaving={isSaving}
          showBack={showBack}
          showNext={showNext}
          showComplete={showComplete}
          nextText={nextText}
          completeText={completeText}
        />
      </div>
    </div>
  );
}

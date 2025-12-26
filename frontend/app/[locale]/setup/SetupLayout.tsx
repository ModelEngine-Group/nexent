 "use client";

import { useState, ReactNode, useEffect } from "react";
import {useTranslation} from "react-i18next";

import { Button, Modal, Input, message, Row, Col } from "antd";
import { configService } from "@/services/configService";
import { configStore } from "@/lib/config";
import { ChevronDown, Globe, Settings } from "lucide-react";
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

  // ModelEngine config modal state
  const [configModalVisible, setConfigModalVisible] = useState(false);
  const [apiKey, setApiKey] = useState("");
  // Whether ModelEngine features are enabled (read from runtime flag or build-time env)
  const [enableModelEngine, setEnableModelEngine] = useState<boolean>(
    typeof process !== "undefined" &&
      (process.env.NEXT_PUBLIC_ENABLE_MODELENGINE || "").toString().toLowerCase() ===
        "true"
  );

  // Read runtime flag injected by server (`/__runtime_config.js`) if available.
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const runtimeVal = (window as any).__MODEL_ENGINE_ENABLED;
      if (typeof runtimeVal !== "undefined") {
        const val =
          runtimeVal === true ||
          String(runtimeVal).toLowerCase() === "true" ||
          String(runtimeVal) === "1";
        setEnableModelEngine(val);
      }
    } catch (e) {
      // ignore errors reading runtime flag
    }
  }, []);

  const openConfigModal = async () => {
    // Only load configuration from backend and echo the ModelEngine API key from that config.
    try {
      await configService.loadConfigToFrontend();
    } catch (e) {
      // ignore load errors; we'll still try to read configStore
    }

    const currentConfig = configStore.getConfig();
    let backendKey = "";
    try {
      backendKey =
        (currentConfig &&
          (currentConfig as any).modelengine &&
          (currentConfig as any).modelengine.apiKey) ||
        "";
    } catch (e) {
      backendKey = "";
    }

    // Echo the backend-provided API key (may be empty string)
    setApiKey(backendKey || "");
    setConfigModalVisible(true);
  };

  const handleSave = async () => {
    try {
      // Update local config
      configStore.updateModelConfig({
        embedding: {
          ...(configStore.getConfig().models?.embedding || {}),
          apiConfig: {
            ...(configStore.getConfig().models?.embedding?.apiConfig || {}),
            apiKey: apiKey || "",
          },
        },
      } as any);

      // Persist to backend - include the modal's ModelEngine API key explicitly
      const currentConfig = configStore.getConfig();
      const payload = {
        ...currentConfig,
        modelengine: { apiKey: apiKey || "" },
      } as any;
      const ok = await configService.saveConfigToBackend(payload);
      if (ok) {
        message.success(t("common.button.save") || t("common.save"));
        // Notify other components that API key/config was saved so they can react (e.g., trigger sync)
        if (typeof window !== "undefined" && window.dispatchEvent) {
          // Update in-memory config store so UI reflects the saved apiKey immediately
          try {
            configStore.updateConfig({ modelengine: { apiKey: apiKey || "" } } as any);
            // Dispatch configChanged for listeners
            window.dispatchEvent(new CustomEvent("configChanged", { detail: { config: configStore.getConfig() } }));
          } catch (e) {
            // ignore store update errors
          }
          // Also emit modelengineApiSaved for backward compatibility (sync handlers)
          window.dispatchEvent(new CustomEvent("modelengineApiSaved", { detail: { apiKey: apiKey || "" } }));
          // Listen once for sync result to keep error handling consistent (but don't duplicate messages)
          const onResult = (ev: any) => {
            // We intentionally do not show messages here to avoid duplicate; handler exists for future extensions.
            window.removeEventListener("modelengineSyncResult", onResult);
          };
          window.addEventListener("modelengineSyncResult", onResult);
        }
      } else {
        message.error(t("common.retryLater"));
      }
    } catch (e) {
      message.error(t("common.retryLater"));
    } finally {
      setConfigModalVisible(false);
    }
  };

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
    <>
      <Row gutter={[16, 16]} align="middle" className="w-full">
        <Col xs={24} className="flex justify-end">
          <div className="flex items-center gap-2">
            {/* ModelEngine config button removed: TopNavbar now provides the configuration modal */}
          </div>
        </Col>
      </Row>

      {/* 配置弹窗：API Key 输入 */}
      <Modal
        title={t("common.button.editConfig")}
        open={configModalVisible}
        onCancel={() => setConfigModalVisible(false)}
        onOk={handleSave}
        okText={t("common.button.save") || t("common.save")}
        cancelText={t("common.cancel")}
        destroyOnClose
      >
        <div className="space-y-3">
          <label className="block mb-1 text-sm font-medium text-gray-700">
            {t("model.dialog.label.apiKey")}
          </label>
          <Input.Password
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={t("model.dialog.placeholder.apiKey")}
            autoComplete="new-password"
          />
        </div>
      </Modal>
    </>
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

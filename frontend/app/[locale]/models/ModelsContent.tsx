"use client";

import React, {useRef, useState} from "react";
import {App} from "antd";
import {motion} from "framer-motion";

import {useSetupFlow} from "@/hooks/useSetupFlow";
import {configStore} from "@/lib/config";
import {configService} from "@/services/configService";
import {
  ConnectionStatus,
} from "@/const/modelConfig";

import AppModelConfig from "./ModelConfiguration";
import {ModelConfigSectionRef} from "./components/modelConfig";
import EmbedderCheckModal from "./components/model/EmbedderCheckModal";

interface ModelsContentProps {
  /** Custom next button handler (optional) */
  onNext?: () => void;
  /** Connection status */
  connectionStatus?: ConnectionStatus;
  /** Is checking connection */
  isCheckingConnection?: boolean;
  /** Check connection callback */
  onCheckConnection?: () => void;
  /** Callback to expose connection status */
  onConnectionStatusChange?: (status: ConnectionStatus) => void;
}

/**
 * ModelsContent - Main component for model configuration
 * Can be used in setup flow or as standalone page
 */
export default function ModelsContent({
  onNext: customOnNext,
  connectionStatus: externalConnectionStatus,
  isCheckingConnection: externalIsCheckingConnection,
  onCheckConnection: externalOnCheckConnection,
  onConnectionStatusChange,
}: ModelsContentProps) {
  const {message} = App.useApp();
  
  // Use custom hook for common setup flow logic
  const {
    canAccessProtectedData,
    pageVariants,
    pageTransition,
    router,
    t,
  } = useSetupFlow({
    requireAdmin: true,
    externalConnectionStatus,
    externalIsCheckingConnection,
    onCheckConnection: externalOnCheckConnection,
    onConnectionStatusChange,
    nonAdminRedirect: "/setup/knowledges",
  });

  const [embeddingModalOpen, setEmbeddingModalOpen] = useState(false);
  const [pendingJump, setPendingJump] = useState(false);
  const [connectivityWarningOpen, setConnectivityWarningOpen] = useState(false);
  const [liveSelectedModels, setLiveSelectedModels] = useState<Record<
    string,
    Record<string, string>
  > | null>(null);
  const modelConfigSectionRef = useRef<ModelConfigSectionRef | null>(null);

  // Centralized behavior: save current config and navigate to next page
  const saveAndNavigateNext = async () => {
    try {
      const currentConfig = configStore.getConfig();
      const ok = await configService.saveConfigToBackend(currentConfig as any);
      if (!ok) {
        message.error(t("setup.page.error.saveConfig"));
      }
    } catch (e) {
      message.error(t("setup.page.error.saveConfig"));
    }
    
    // Call custom onNext if provided, otherwise navigate to default next page
    if (customOnNext) {
      customOnNext();
    } else {
      router.push("/setup/knowledges");
    }
  };

  const handleEmbeddingOk = async () => {
    setEmbeddingModalOpen(false);
    if (pendingJump) {
      setPendingJump(false);
      await saveAndNavigateNext();
    }
  };

  const handleConnectivityOk = async () => {
    setConnectivityWarningOpen(false);
    if (pendingJump) {
      setPendingJump(false);
      // Apply live selections programmatically to mimic dropdown onChange
      try {
        const ref = modelConfigSectionRef.current;
        const selections = liveSelectedModels || {};
        if (ref && selections) {
          // Iterate categories and options
          for (const [category, options] of Object.entries(selections)) {
            for (const [option, displayName] of Object.entries(options)) {
              if (displayName) {
                // Simulate dropdown change and trigger onChange flow
                await ref.simulateDropdownChange(category, option, displayName);
              }
            }
          }
        }
      } catch (e) {
        message.error(t("setup.page.error.saveConfig"));
      }
      await saveAndNavigateNext();
    }
  };

  return (
    <>
      <motion.div
        initial="initial"
        animate="in"
        exit="out"
        variants={pageVariants}
        transition={pageTransition}
        style={{width: "100%", height: "100%"}}
      >
        <div className="w-full h-full flex items-center justify-center">
          {canAccessProtectedData ? (
            <AppModelConfig
              onSelectedModelsChange={(selected) =>
                setLiveSelectedModels(selected)
              }
              onEmbeddingConnectivityChange={() => {}}
              forwardedRef={modelConfigSectionRef}
              canAccessProtectedData={canAccessProtectedData}
            />
          ) : null}
        </div>
      </motion.div>

      <EmbedderCheckModal
        emptyWarningOpen={embeddingModalOpen}
        onEmptyOk={handleEmbeddingOk}
        onEmptyCancel={() => setEmbeddingModalOpen(false)}
        connectivityWarningOpen={connectivityWarningOpen}
        onConnectivityOk={handleConnectivityOk}
        onConnectivityCancel={() => setConnectivityWarningOpen(false)}
        modifyWarningOpen={false}
        onModifyOk={() => {}}
        onModifyCancel={() => {}}
      />
    </>
  );
}


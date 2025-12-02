"use client";

import React, {useEffect} from "react";
import {motion} from "framer-motion";

import {useSetupFlow} from "@/hooks/useSetupFlow";
import {configService} from "@/services/configService";
import {configStore} from "@/lib/config";
import {
  USER_ROLES,
  ConnectionStatus,
} from "@/const/modelConfig";
import log from "@/lib/logger";

import DataConfig from "./KnowledgeBaseConfiguration";

interface KnowledgesContentProps {
  /** Whether currently saving */
  isSaving: boolean;
  /** Connection status */
  connectionStatus?: ConnectionStatus;
  /** Is checking connection */
  isCheckingConnection?: boolean;
  /** Check connection callback */
  onCheckConnection?: () => void;
  /** Callback to expose connection status */
  onConnectionStatusChange?: (status: ConnectionStatus) => void;
  /** Callback to expose saving state */
  onSavingStateChange?: (isSaving: boolean) => void;
}

/**
 * KnowledgesContent - Main component for knowledge base configuration
 * Can be used in setup flow or as standalone page
 */
export default function KnowledgesContent({
  isSaving = false,
  connectionStatus: externalConnectionStatus,
  isCheckingConnection: externalIsCheckingConnection,
  onCheckConnection: externalOnCheckConnection,
  onConnectionStatusChange,
  onSavingStateChange,
}: KnowledgesContentProps) {
  
  // Use custom hook for common setup flow logic
  const {
    user,
    isSpeedMode,
    canAccessProtectedData,
    pageVariants,
    pageTransition,
  } = useSetupFlow({
    requireAdmin: false, // Knowledge base accessible to all users
    externalConnectionStatus,
    externalIsCheckingConnection,
    onCheckConnection: externalOnCheckConnection,
    onConnectionStatusChange,
  });
  
  // Update external saving state
  useEffect(() => {
    onSavingStateChange?.(isSaving);
  }, [isSaving, onSavingStateChange]);

  // Knowledge base specific initialization
  useEffect(() => {
    if (!canAccessProtectedData) return;

    // Trigger knowledge base data acquisition when the page is initialized
    window.dispatchEvent(
      new CustomEvent("knowledgeBaseDataUpdated", {
        detail: {forceRefresh: true},
      })
    );

    // Load config for normal user
    const loadConfigForNormalUser = async () => {
      if (!isSpeedMode && user && user.role !== USER_ROLES.ADMIN) {
        try {
          await configService.loadConfigToFrontend();
          configStore.reloadFromStorage();
        } catch (error) {
          log.error("Failed to load config:", error);
        }
      }
    };

    loadConfigForNormalUser();
  }, [canAccessProtectedData, externalOnCheckConnection]);

  return (
    <>
      {canAccessProtectedData ? (
        <motion.div
          initial="initial"
          animate="in"
          exit="out"
          variants={pageVariants}
          transition={pageTransition}
          style={{width: "100%", height: "100%"}}
        >
          <div className="w-full h-full flex items-center justify-center">
            <DataConfig isActive={true} />
          </div>
        </motion.div>
      ) : null}
    </>
  );
}


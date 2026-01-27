"use client";

import React, { useEffect } from "react";
import { motion } from "framer-motion";

import { useSetupFlow } from "@/hooks/useSetupFlow";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { configService } from "@/services/configService";
import { configStore } from "@/lib/config";
import { USER_ROLES } from "@/const/auth";
import log from "@/lib/logger";

import DataConfig from "./KnowledgeBaseConfiguration";

/**
 * KnowledgesContent - Main component for knowledge base configuration
 * Can be used in setup flow or as standalone page
 */
export default function KnowledgesContent() {
  // Use custom hook for common setup flow logic
  const { pageVariants, pageTransition } = useSetupFlow({
    requireAdmin: false, // Knowledge base accessible to all users
  });

  // Get auth state directly from providers
  const { isSpeedMode } = useDeployment();
  const { user } = useAuthorizationContext();

  // Knowledge base specific initialization
  useEffect(() => {
    // Trigger knowledge base data acquisition when the page is initialized
    window.dispatchEvent(
      new CustomEvent("knowledgeBaseDataUpdated", {
        detail: { forceRefresh: true },
      })
    );

    // Load config for normal user
    const loadConfigForNormalUser = async () => {
      if (!isSpeedMode && user) {
        try {
          await configService.loadConfigToFrontend();
          configStore.reloadFromStorage();
        } catch (error) {
          log.error("Failed to load config:", error);
        }
      }
    };

    loadConfigForNormalUser();
  }, [isSpeedMode, user]);

  return (
    <div className="w-full h-full p-8">
      <motion.div
        initial="initial"
        animate="in"
        exit="out"
        variants={pageVariants}
        transition={pageTransition}
        style={{ width: "100%", height: "100%" }}
      >
        <div className="w-full h-full flex items-center justify-center">
          <DataConfig isActive={true} />
        </div>
      </motion.div>
    </div>
  );
}

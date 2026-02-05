"use client";

import React, { useEffect } from "react";
import { motion } from "framer-motion";

import { useSetupFlow } from "@/hooks/useSetupFlow";
import { configService } from "@/services/configService";
import { configStore } from "@/lib/config";
import { USER_ROLES } from "@/const/auth";
import log from "@/lib/logger";
import knowledgeBaseService from "@/services/knowledgeBaseService";

import DataConfig from "./KnowledgeBaseConfiguration";

/**
 * KnowledgesContent - Main component for knowledge base configuration
 * Can be used in setup flow or as standalone page
 */
export default function KnowledgesContent() {
  // Use custom hook for common setup flow logic
  const {
    user,
    isSpeedMode,
    pageVariants,
    pageTransition,
    canAccessProtectedData,
  } = useSetupFlow({
    requireAdmin: false, // Knowledge base accessible to all users
  });

  // Knowledge base specific initialization
  useEffect(() => {
    // Trigger knowledge base data acquisition when the page is initialized
    window.dispatchEvent(
      new CustomEvent("knowledgeBaseDataUpdated", {
        detail: { forceRefresh: true },
      })
    );

    // Load knowledge base list from API
    const loadKnowledgeBaseList = async () => {
      try {
        await knowledgeBaseService.getKnowledgeBases(true);
      } catch (error) {
        log.error("Failed to load knowledge base list:", error);
      }
    };

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

    loadKnowledgeBaseList();
    loadConfigForNormalUser();
  }, [isSpeedMode, user]);

  return (
    <>
      <div className="w-full h-full p-8">
        {canAccessProtectedData ? (
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
        ) : null}
      </div>
    </>
  );
}

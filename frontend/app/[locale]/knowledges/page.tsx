"use client";

import React, { useEffect } from "react";
import { motion } from "framer-motion";

import { useSetupFlow } from "@/hooks/useSetupFlow";
import { useDeployment } from "@/components/providers/deploymentProvider";
import log from "@/lib/logger";
import knowledgeBaseService from "@/services/knowledgeBaseService";

import DataConfig from "./KnowledgeBaseConfiguration";

/**
 * KnowledgesContent - Main component for knowledge base configuration
 * Can be used in setup flow or as standalone page
 */
export default function KnowledgesContent() {
  // Get user and deployment state from respective hooks
  const { isSpeedMode } = useDeployment();

  // Use custom hook for common setup flow logic
  const {
    pageVariants,
    pageTransition,
  } = useSetupFlow();

  // Knowledge base specific initialization
  useEffect(() => {
    // Trigger knowledge base data acquisition when the page is initialized
    window.dispatchEvent(
      new CustomEvent("knowledgeBaseDataUpdated", {
        detail: { forceRefresh: true },
      })
    );

    const loadKnowledgeBaseList = async () => {
      try {
        await knowledgeBaseService.getKnowledgeBases(true);
      } catch (error) {
        log.error("Failed to load knowledge base list:", error);
      }
    };

    loadKnowledgeBaseList();
  }, [isSpeedMode]);

  return (
    <>
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
    </>
  );
}

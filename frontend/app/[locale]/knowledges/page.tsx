"use client";

import React, { useEffect } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";

import { useSetupFlow } from "@/hooks/useSetupFlow";
import { useDeployment } from "@/components/providers/deploymentProvider";
import log from "@/lib/logger";
import knowledgeBaseService from "@/services/knowledgeBaseService";

import DataConfig from "./KnowledgeBaseConfiguration";
import AidpKnowledgeConfiguration from "@/ext_components/aidp/components/AidpKnowledgeConfiguration";

/**
 * KnowledgesContent - Unified knowledge base entry page
 *
 * Renders the AIDP knowledge base configuration component when the
 * ENABLE_AIDP_KNOWLEDGE flag is enabled, otherwise renders the built-in
 * local knowledge base component. A single `/knowledges` route serves
 * both backends from the user's perspective; the sidebar menu label is
 * "知识库配置" regardless of which backend is active.
 *
 * Loading state: while the deployment config is being fetched, a minimal
 * loading placeholder is shown to prevent the wrong component from
 * flashing on screen before the flag is resolved.
 */
export default function KnowledgesContent() {
  const { enableAidpKnowledge, isDeploymentReady } = useDeployment();
  const router = useRouter();

  const { pageVariants, pageTransition } = useSetupFlow();

  // Local KB only: initialize knowledge base service data
  useEffect(() => {
    // Skip local KB initialization when AIDP is active
    if (!isDeploymentReady || enableAidpKnowledge) {
      return;
    }

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
  }, [isDeploymentReady, enableAidpKnowledge]);

  // Loading state: wait for deployment config before deciding which
  // component to render. Prevents flashing of the local KB page when
  // AIDP is actually enabled.
  if (!isDeploymentReady) {
    return (
      <div className="w-full h-full flex items-center justify-center">
        <div className="text-sm text-gray-400">Loading...</div>
      </div>
    );
  }

  // AIDP branch: render AIDP knowledge base configuration
  if (enableAidpKnowledge) {
    return (
      <div style={{ width: "100%", height: "100%", padding: "0 20px" }}>
        <motion.div
          initial="initial"
          animate="in"
          exit="out"
          variants={pageVariants}
          transition={pageTransition}
          style={{ width: "100%", height: "100%" }}
        >
          <AidpKnowledgeConfiguration />
        </motion.div>
      </div>
    );
  }

  // Local knowledge base branch
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

"use client";

import React, { useEffect } from "react";
import { motion } from "framer-motion";

import { useSetupFlow } from "@/hooks/useSetupFlow";

import UnifiedKnowledgeBaseView from "@/components/knowledge-base/UnifiedKnowledgeBaseView";

/**
 * KnowledgesContent - Main component for knowledge base configuration.
 *
 * Renders the unified knowledge base management view (Phase 3 architecture).
 * The view handles:
 * - Adapter list (local + external)
 * - KB list with Tab filter (all / local / external)
 * - KB creation via 2-step modal (select adapter -> fill form)
 * - KB detail drawer with document management
 */
export default function KnowledgesContent() {
  // Use custom hook for common setup flow logic (page transitions)
  const { pageVariants, pageTransition } = useSetupFlow();

  // Dispatch legacy event for backward compatibility with old components
  // that might still listen to this (e.g., polling service, sidebar).
  useEffect(() => {
    window.dispatchEvent(
      new CustomEvent("knowledgeBaseDataUpdated", {
        detail: { forceRefresh: true },
      })
    );
  }, []);

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
        <UnifiedKnowledgeBaseView defaultTab="all" />
      </motion.div>
    </div>
  );
}

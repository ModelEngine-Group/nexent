"use client";

import React from "react";
import { motion } from "framer-motion";

import { useSetupFlow } from "@/hooks/useSetupFlow";

import AidpKnowledgeDetailPage from "@/ext_components/aidp/components/AidpKnowledgeDetailPage";

/**
 * Dedicated AIDP knowledge base detail entry.
 *
 * The page renders the AIDP detail view for the `kb` query parameter; the
 * component sends a visitor back to the knowledge base overview when the
 * deployment does not have the AIDP backend enabled. The dedicated route
 * keeps the detail URL stable across browser refreshes, and the existing
 * `knowledges` entry behavior for the list view is untouched.
 */
export default function KnowledgeBaseDetailContent() {
  const { pageVariants, pageTransition } = useSetupFlow();

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
        <AidpKnowledgeDetailPage />
      </motion.div>
    </div>
  );
}

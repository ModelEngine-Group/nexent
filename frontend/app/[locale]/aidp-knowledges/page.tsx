"use client";

import React from "react";
import { motion } from "framer-motion";

import { useSetupFlow } from "@/hooks/useSetupFlow";

import AidpKnowledgeConfiguration from "./AidpKnowledgeConfiguration";

/**
 * AIDP Knowledge Base configuration page entry.
 * Thin wrapper that provides page transition animation.
 */
export default function AidpKnowledgePage() {
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
        <AidpKnowledgeConfiguration />
      </motion.div>
    </div>
  );
}

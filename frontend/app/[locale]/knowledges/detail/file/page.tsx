// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React from "react";
import { motion } from "framer-motion";

import { useSetupFlow } from "@/hooks/useSetupFlow";

import AidpFileDetailPage from "@/ext_components/aidp/pages/knowledge-file-detail/AidpFileDetailPage";

/**
 * Dedicated AIDP file detail entry.
 *
 * The file opens as its own page (`kb` + `file` query parameters) instead of
 * replacing the file list inside the knowledge base detail view. Refreshing,
 * deep linking and the browser back button therefore follow normal page
 * semantics, and the knowledge base header/tabs are not rendered here.
 */
export default function KnowledgeBaseFileDetailContent() {
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
        <AidpFileDetailPage />
      </motion.div>
    </div>
  );
}

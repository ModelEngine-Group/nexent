"use client";

import React, { useEffect } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";

import { useSetupFlow } from "@/hooks/useSetupFlow";
import { useDeployment } from "@/components/providers/deploymentProvider";

import AidpKnowledgeConfiguration from "@/ext_components/aidp/components/AidpKnowledgeConfiguration";

/**
 * AIDP Knowledge Base configuration page entry.
 * Thin wrapper that provides page transition animation.
 * Redirects to home when the AIDP knowledge feature is disabled via env var.
 */
export default function AidpKnowledgePage() {
  const { pageVariants, pageTransition } = useSetupFlow();
  const { enableAidpKnowledge, isDeploymentReady } = useDeployment();
  const router = useRouter();

  // Redirect to home when AIDP knowledge feature is disabled
  useEffect(() => {
    if (isDeploymentReady && !enableAidpKnowledge) {
      router.replace("/");
    }
  }, [isDeploymentReady, enableAidpKnowledge, router]);

  // Render nothing while deployment info is loading or feature is disabled
  if (!isDeploymentReady || !enableAidpKnowledge) {
    return null;
  }

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

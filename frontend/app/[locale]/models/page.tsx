"use client";

import { useRef } from "react";
import { motion } from "framer-motion";

import { useSetupFlow } from "@/hooks/useSetupFlow";

import AppModelConfig from "./ModelConfiguration";
import { ModelConfigSectionRef } from "./components/modelConfig";

/**
 * ModelsContent - Main component for model configuration
 * Can be used in setup flow or as standalone page
 */
export default function ModelsContent() {
  // Use custom hook for common setup flow logic
  const { pageVariants, pageTransition } = useSetupFlow({});

  const modelConfigSectionRef = useRef<ModelConfigSectionRef | null>(null);

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
          <AppModelConfig
            forwardedRef={modelConfigSectionRef}
          />
        </div>
      </motion.div>
    </div>
  );
}

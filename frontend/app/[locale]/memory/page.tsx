"use client";

import { motion } from "framer-motion";

import { SETUP_PAGE_CONTAINER } from "@/const/layoutConstants";
import { useSetupFlow } from "@/hooks/useSetupFlow";

import { MemoryManager } from "./MemoryManager";
import "./memory.css";

export default function MemoryContent() {
  const { pageVariants, pageTransition } = useSetupFlow();

  return (
    <div className="w-full h-full p-8">
      <motion.div
        initial="initial"
        animate="in"
        exit="out"
        variants={pageVariants}
        transition={pageTransition}
        className="memory-page"
      >
        <div
          className="memory-page-inner"
          style={{
            maxWidth: SETUP_PAGE_CONTAINER.MAX_WIDTH,
            padding: `0 ${SETUP_PAGE_CONTAINER.HORIZONTAL_PADDING}`,
          }}
        >
          <MemoryManager />
        </div>
      </motion.div>
    </div>
  );
}

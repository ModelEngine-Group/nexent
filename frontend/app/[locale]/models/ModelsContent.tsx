"use client";

import {useRef} from "react";
import {motion} from "framer-motion";

import {useSetupFlow} from "@/hooks/useSetupFlow";
import {
  ConnectionStatus,
} from "@/const/modelConfig";

import AppModelConfig from "./ModelConfiguration";
import {ModelConfigSectionRef} from "./components/modelConfig";

interface ModelsContentProps {
  /** Custom next button handler (optional) */
  onNext?: () => void;
  /** Connection status */
  connectionStatus?: ConnectionStatus;
  /** Is checking connection */
  isCheckingConnection?: boolean;
  /** Check connection callback */
  onCheckConnection?: () => void;
  /** Callback to expose connection status */
  onConnectionStatusChange?: (status: ConnectionStatus) => void;
}

/**
 * ModelsContent - Main component for model configuration
 * Can be used in setup flow or as standalone page
 */
export default function ModelsContent({
  connectionStatus: externalConnectionStatus,
  isCheckingConnection: externalIsCheckingConnection,
  onCheckConnection: externalOnCheckConnection,
  onConnectionStatusChange,
}: ModelsContentProps) {
  // Use custom hook for common setup flow logic
  const {
    canAccessProtectedData,
    pageVariants,
    pageTransition,
  } = useSetupFlow({
    requireAdmin: true,
    externalConnectionStatus,
    externalIsCheckingConnection,
    onCheckConnection: externalOnCheckConnection,
    onConnectionStatusChange,
    nonAdminRedirect: "/setup/knowledges",
  });

  const modelConfigSectionRef = useRef<ModelConfigSectionRef | null>(null);

  return (
    <>
      <motion.div
        initial="initial"
        animate="in"
        exit="out"
        variants={pageVariants}
        transition={pageTransition}
        style={{width: "100%", height: "100%"}}
      >
        <div className="w-full h-full flex items-center justify-center">
          {canAccessProtectedData ? (
            <AppModelConfig
              onSelectedModelsChange={() => {}}
              onEmbeddingConnectivityChange={() => {}}
              forwardedRef={modelConfigSectionRef}
              canAccessProtectedData={canAccessProtectedData}
            />
          ) : null}
        </div>
      </motion.div>

    </>
  );
}


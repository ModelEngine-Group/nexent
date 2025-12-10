"use client";

import React, {useState, useEffect, useRef, forwardRef, useImperativeHandle} from "react";
import {motion} from "framer-motion";

import {useSetupFlow} from "@/hooks/useSetupFlow";
import {
  ConnectionStatus,
} from "@/const/modelConfig";

import AgentConfig, {AgentConfigHandle} from "./AgentConfiguration";
import SaveConfirmModal from "./components/SaveConfirmModal";

interface AgentsContentProps {
  /** Whether currently saving */
  isSaving?: boolean;
  /** Connection status */
  connectionStatus?: ConnectionStatus;
  /** Is checking connection */
  isCheckingConnection?: boolean;
  /** Check connection callback */
  onCheckConnection?: () => void;
  /** Callback to expose connection status */
  onConnectionStatusChange?: (status: ConnectionStatus) => void;
  /** Callback to expose saving state */
  onSavingStateChange?: (isSaving: boolean) => void;
}

/**
 * AgentsContent - Main component for agent configuration
 * Can be used in setup flow or as standalone page
 */
export default forwardRef<AgentConfigHandle, AgentsContentProps>(function AgentsContent({
  isSaving: externalIsSaving,
  connectionStatus: externalConnectionStatus,
  isCheckingConnection: externalIsCheckingConnection,
  onCheckConnection: externalOnCheckConnection,
  onConnectionStatusChange,
  onSavingStateChange,
}: AgentsContentProps, ref) {
  const agentConfigRef = useRef<AgentConfigHandle | null>(null);
  const [showSaveConfirm, setShowSaveConfirm] = useState(false);
  const pendingNavRef = useRef<null | (() => void)>(null);
  
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

  const [internalIsSaving, setInternalIsSaving] = useState(false);
  const isSaving = externalIsSaving ?? internalIsSaving;

  // Expose AgentConfigHandle methods to parent
  useImperativeHandle(ref, () => ({
    hasUnsavedChanges: () => agentConfigRef.current?.hasUnsavedChanges?.() ?? false,
    saveAllChanges: async () => {
      if (agentConfigRef.current?.saveAllChanges) {
        await agentConfigRef.current.saveAllChanges();
      }
    },
    reloadCurrentAgentData: async () => {
      if (agentConfigRef.current?.reloadCurrentAgentData) {
        await agentConfigRef.current.reloadCurrentAgentData();
      }
    },
  }), []);

  // Update external saving state
  useEffect(() => {
    onSavingStateChange?.(isSaving);
  }, [isSaving, onSavingStateChange]);

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
        <div className="w-full h-full">
          {canAccessProtectedData ? (
            <AgentConfig ref={agentConfigRef} canAccessProtectedData={canAccessProtectedData} />
          ) : null}
        </div>
      </motion.div>

      <SaveConfirmModal
        open={showSaveConfirm}
        onCancel={async () => {
          // Reload data from backend to discard changes
          await agentConfigRef.current?.reloadCurrentAgentData?.();
          setShowSaveConfirm(false);
          const go = pendingNavRef.current;
          pendingNavRef.current = null;
          if (go) go();
        }}
        onSave={async () => {
          try {
            setInternalIsSaving(true);
            await agentConfigRef.current?.saveAllChanges?.();
            setShowSaveConfirm(false);
            const go = pendingNavRef.current;
            pendingNavRef.current = null;
            if (go) go();
          } catch (e) {
            // errors are surfaced by underlying save
          } finally {
            setInternalIsSaving(false);
          }
        }}
      />
    </>
  );
});


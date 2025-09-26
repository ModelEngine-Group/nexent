"use client";

import React, {useEffect, useRef, useState} from "react";
import {useRouter} from "next/navigation";
import {useTranslation} from "react-i18next";

import {App, Button} from "antd";
import {motion} from "framer-motion";

import {useAuth} from "@/hooks/useAuth";
import modelEngineService from "@/services/modelEngineService";
import {configStore} from "@/lib/config";
import { configService } from "@/services/configService";
import {
  CONNECTION_STATUS,
  ConnectionStatus,
  MODEL_STATUS,
} from "@/const/modelConfig";
import log from "@/lib/logger";

import SetupLayout from "../SetupLayout";
import AppModelConfig from "./config";
import { ModelConfigSectionRef } from "./components/modelConfig";
import EmbedderCheckModal from "./components/model/EmbedderCheckModal";

export default function ModelSetupPage() {
  const { message } = App.useApp();
  const router = useRouter();
  const { t } = useTranslation();
  const { user, isLoading: userLoading } = useAuth();

  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>(
    CONNECTION_STATUS.PROCESSING
  );
  const [isCheckingConnection, setIsCheckingConnection] = useState(false);
  const [embeddingModalOpen, setEmbeddingModalOpen] = useState(false);
  const [pendingJump, setPendingJump] = useState(false);
  const [connectivityWarningOpen, setConnectivityWarningOpen] = useState(false);
  const [liveSelectedModels, setLiveSelectedModels] = useState<Record<
    string,
    Record<string, string>
  > | null>(null);
  const [embeddingConnectivity, setEmbeddingConnectivity] = useState<{
    embedding?: string;
  } | null>(null);
  const modelConfigSectionRef = useRef<ModelConfigSectionRef | null>(null);

  // Check login status and permission
  useEffect(() => {
    if (!userLoading && !user) {
      router.push("/");
      return;
    }
  }, [user, userLoading, router]);

  // Check the connection status when the page is initialized
  useEffect(() => {
    checkModelEngineConnection();
  }, []);

  // Function to check the ModelEngine connection status
  const checkModelEngineConnection = async () => {
    setIsCheckingConnection(true);

    try {
      const result = await modelEngineService.checkConnection();
      setConnectionStatus(result.status);
    } catch (error) {
      log.error(t("setup.page.error.checkConnection"), error);
      setConnectionStatus(CONNECTION_STATUS.ERROR);
    } finally {
      setIsCheckingConnection(false);
    }
  };

  // Centralized behavior: save current config and navigate to next page
  const saveAndNavigateNext = async () => {
    try {
      const currentConfig = configStore.getConfig();
      const ok = await configService.saveConfigToBackend(currentConfig as any);
      if (!ok) {
        message.error(t("setup.page.error.saveConfig"));
      }
    } catch (e) {
      message.error(t("setup.page.error.saveConfig"));
    }
    router.push("/setup/knowledges");
  };

  // Handle next button click
  const handleNext = async () => {
    try {
      // Get the current configuration
      const currentConfig = configStore.getConfig();

      // Check the main model
      if (!currentConfig.models.llm.modelName) {
        message.error(t("setup.page.error.selectMainModel"));

        // Trigger a custom event to notify the ModelConfigSection to mark the main model dropdown as an error
        window.dispatchEvent(
          new CustomEvent("highlightMissingField", {
            detail: { field: t("setup.page.error.highlightField.llmMain") },
          })
        );

        return;
      }

      // Check embedding model using live selection from current UI, not the stored config
      const hasEmbeddingLive =
        !!liveSelectedModels?.embedding?.embedding ||
        !!liveSelectedModels?.embedding?.multi_embedding;
      if (!hasEmbeddingLive) {
        setEmbeddingModalOpen(true);
        setPendingJump(true);
        // Highlight embedding dropdown
        window.dispatchEvent(
          new CustomEvent("highlightMissingField", {
            detail: { field: "embedding.embedding" },
          })
        );
        return;
      }

      // connectivity check for embedding models
      const connectivityOk = isEmbeddingConnectivityOk();
      if (!connectivityOk) {
        setConnectivityWarningOpen(true);
        setPendingJump(true);
        return;
      }

      await saveAndNavigateNext();
    } catch (error) {
      log.error(t("setup.page.error.systemError"), error);
      message.error(t("setup.page.error.systemError"));
    }
  };

  const handleEmbeddingOk = async () => {
    setEmbeddingModalOpen(false);
    if (pendingJump) {
      setPendingJump(false);
      await saveAndNavigateNext();
    }
  };

  // Check embedding connectivity for selected models
  const isEmbeddingConnectivityOk = (): boolean => {
    // can add multi_embedding in future
    const selectedEmbedding = liveSelectedModels?.embedding?.embedding || "";
    if (!selectedEmbedding) return true;
    const embStatus = embeddingConnectivity?.embedding;
    const ok = (s?: string) => !s || s === MODEL_STATUS.AVAILABLE;
    return ok(embStatus);
  };

  const handleConnectivityOk = async () => {
    setConnectivityWarningOpen(false);
    if (pendingJump) {
      setPendingJump(false);
      // Apply live selections programmatically to mimic dropdown onChange
      try {
        const ref = modelConfigSectionRef.current;
        const selections = liveSelectedModels || {};
        if (ref && selections) {
          // Iterate categories and options
          for (const [category, options] of Object.entries(selections)) {
            for (const [option, displayName] of Object.entries(options)) {
              if (displayName) {
                // Simulate dropdown change and trigger onChange flow
                await ref.simulateDropdownChange(category, option, displayName);
              }
            }
          }
        }
      } catch (e) {
        message.error(t("setup.page.error.saveConfig"));
      }
      await saveAndNavigateNext();
    }
  };

  // Animation variants for smooth transitions
  const pageVariants = {
    initial: {
      opacity: 0,
      x: 20,
    },
    in: {
      opacity: 1,
      x: 0,
    },
    out: {
      opacity: 0,
      x: -20,
    },
  };

  const pageTransition = {
    type: "tween" as const,
    ease: "anticipate" as const,
    duration: 0.4,
  };

  return (
    <SetupLayout
      connectionStatus={connectionStatus}
      isCheckingConnection={isCheckingConnection}
      onCheckConnection={checkModelEngineConnection}
      title={t("setup.header.title")}
      description={t("setup.header.description")}
      onNext={handleNext}
      showNext={true}
      nextText={t("setup.navigation.button.next")}
    >
      <motion.div
        initial="initial"
        animate="in"
        exit="out"
        variants={pageVariants}
        transition={pageTransition}
        style={{ width: "100%", height: "100%" }}
      >
        <AppModelConfig
          onSelectedModelsChange={(selected) => setLiveSelectedModels(selected)}
          onEmbeddingConnectivityChange={(status) =>
            setEmbeddingConnectivity(status)
          }
          forwardedRef={modelConfigSectionRef}
        />
      </motion.div>

      <EmbedderCheckModal
        emptyWarningOpen={embeddingModalOpen}
        onEmptyOk={handleEmbeddingOk}
        onEmptyCancel={() => setEmbeddingModalOpen(false)}
        connectivityWarningOpen={connectivityWarningOpen}
        onConnectivityOk={handleConnectivityOk}
        onConnectivityCancel={() => setConnectivityWarningOpen(false)}
        modifyWarningOpen={false}
        onModifyOk={() => {}}
        onModifyCancel={() => {}}
      />
    </SetupLayout>
  );
}

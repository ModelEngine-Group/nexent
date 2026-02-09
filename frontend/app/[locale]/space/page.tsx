"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { App } from "antd";
import { Plus, RefreshCw, Upload } from "lucide-react";

import { useSetupFlow } from "@/hooks/useSetupFlow";
import { usePublishedAgentList } from "@/hooks/agent/usePublishedAgentList";
import { Agent } from "@/types/agentConfig";
import AgentCard from "./components/AgentCard";
import { ImportAgentData } from "@/hooks/useAgentImport";
import AgentImportWizard from "@/components/agent/AgentImportWizard";
import log from "@/lib/logger";

/**
 * Agent Space page component
 * Displays agent cards grid and management controls
 */
export default function SpacePage() {
  const router = useRouter();

  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const { pageVariants, pageTransition } = useSetupFlow();
  const [isImporting, setIsImporting] = useState(false);
  const { agents, isLoading, invalidate } = usePublishedAgentList();

  // Import wizard state
  const [importWizardVisible, setImportWizardVisible] = useState(false);
  const [importWizardData, setImportWizardData] =
    useState<ImportAgentData | null>(null);


  const handleCreateAgent = () => {
    router.push("/agents?create=true");
  };

  const onRefresh = () => {
    invalidate();
  };

  const onImportAgent = () => {
    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.accept = ".json";
    fileInput.onchange = async (event) => {
      const file = (event.target as HTMLInputElement).files?.[0];
      if (!file) return;

      if (!file.name.endsWith(".json")) {
        message.error(t("businessLogic.config.error.invalidFileType"));
        return;
      }

      try {
        // Read and parse file
        const fileContent = await file.text();
        let agentData: ImportAgentData;

        try {
          agentData = JSON.parse(fileContent);
        } catch (parseError) {
          message.error(t("businessLogic.config.error.invalidFileType"));
          return;
        }

        // Validate structure
        if (!agentData.agent_id || !agentData.agent_info) {
          message.error(t("businessLogic.config.error.invalidFileType"));
          return;
        }

        // Open wizard with parsed data
        setImportWizardData(agentData);
        setImportWizardVisible(true);
      } catch (error) {
        log.error("Failed to read import file:", error);
        message.error(t("businessLogic.config.error.agentImportFailed"));
      }
    };

    fileInput.click();
  };


  return (
    <div className="w-full h-full">
      <motion.div
        initial="initial"
        animate="in"
        exit="out"
        variants={pageVariants}
        transition={pageTransition}
        className="w-full px-4 md:px-8 lg:px-16 py-8 h-full"
      >
        <div className="max-w-7xl mx-auto">
          {/* Page header */}
          <div className="flex items-center justify-between mb-6">
            <motion.div
              initial={{ opacity: 0, y: -20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5 }}
            >
              <h1 className="text-3xl font-bold text-blue-600 dark:text-blue-500">
                {t("space.title", "Agent Space")}
              </h1>
              <p className="text-slate-600 dark:text-slate-300 mt-2">
                {t(
                  "space.description",
                  "Manage and interact with your intelligent agents"
                )}
              </p>
            </motion.div>

            {/* Refresh button */}
            <motion.div
              initial={{ opacity: 0, y: -20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: 0.1 }}
            >
              <button
                onClick={onRefresh}
                disabled={isLoading}
                className="p-2 rounded-md hover:bg-blue-50 dark:hover:bg-blue-900/20 text-slate-600 dark:text-slate-300 hover:text-blue-600 dark:hover:text-blue-400 transition-colors disabled:opacity-50"
                title={t("common.refresh", "Refresh")}
              >
                <RefreshCw
                  className={`h-5 w-5 ${isLoading ? "animate-spin" : ""}`}
                />
              </button>
            </motion.div>
          </div>

          {/* Agent cards grid */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.5, delay: 0.2 }}
            className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 pb-8"
          >
            {/* Create/Import agent card - only for admin */}
              <motion.div
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ duration: 0.3, delay: 0.3 }}
                className="aspect-[4/3]"
              >
                <div className="w-full h-full flex flex-col gap-2">
                  {/* Create new agent - top half */}
                  <button
                    onClick={handleCreateAgent}
                    className="flex-1 border-2 border-dashed border-blue-300 dark:border-blue-600 rounded-lg hover:border-blue-500 dark:hover:border-blue-400 bg-blue-50 dark:bg-blue-900/20 hover:bg-blue-100 dark:hover:bg-blue-900/40 transition-all duration-300 flex flex-col items-center justify-center gap-2 group"
                  >
                    <div className="w-12 h-12 rounded-full bg-blue-100 dark:bg-blue-900/40 flex items-center justify-center group-hover:bg-blue-200 dark:group-hover:bg-blue-900/60 transition-colors">
                      <Plus className="h-6 w-6 text-blue-500 group-hover:text-blue-600 dark:text-blue-400 dark:group-hover:text-blue-300" />
                    </div>
                    <span className="text-sm font-medium text-blue-600 dark:text-blue-400 group-hover:text-blue-700 dark:group-hover:text-blue-300">
                      {t("space.createAgent", "Create New Agent")}
                    </span>
                  </button>

                  {/* Import agent - bottom half */}
                  <button
                    onClick={onImportAgent}
                    disabled={isImporting}
                    className="flex-1 border-2 border-dashed border-green-300 dark:border-green-600 rounded-lg hover:border-green-500 dark:hover:border-green-400 bg-green-50 dark:bg-green-900/20 hover:bg-green-100 dark:hover:bg-green-900/40 transition-all duration-300 flex flex-col items-center justify-center gap-2 group disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <div className="w-12 h-12 rounded-full bg-green-100 dark:bg-green-900/40 flex items-center justify-center group-hover:bg-green-200 dark:group-hover:bg-green-900/60 transition-colors">
                      <Upload className="h-6 w-6 text-green-500 group-hover:text-green-600 dark:text-green-400 dark:group-hover:text-green-300" />
                    </div>
                    <span className="text-sm font-medium text-green-600 dark:text-green-400 group-hover:text-green-700 dark:group-hover:text-green-300">
                      {isImporting
                        ? t("subAgentPool.button.importing", "Importing...")
                        : t("subAgentPool.button.import", "Import Agent")}
                    </span>
                  </button>
                </div>
              </motion.div>

            {/* Agent cards */}
            {agents.map((agent: Agent, index: number) => (
              <motion.div
                key={agent.id}
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ duration: 0.3, delay: 0.3 + (index + 1) * 0.05 }}
                className="aspect-[4/3]"
              >
                <AgentCard agent={agent} onRefresh={onRefresh} />
              </motion.div>
            ))}
          </motion.div>

          {/* Empty state */}
          {!isLoading && agents.length === 0 && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.5, delay: 0.4 }}
              className="text-center py-16"
            >
              <p className="text-slate-500 dark:text-slate-400">
                {t(
                  "space.noAgents",
                  "No agents yet. Create your first agent to get started!"
                )}
              </p>
            </motion.div>
          )}
        </div>
      </motion.div>

      {/* Import Wizard Modal */}
      <AgentImportWizard
        visible={importWizardVisible}
        onCancel={() => {
          setImportWizardVisible(false);
          setImportWizardData(null);
        }}
        initialData={importWizardData}
        onImportComplete={() => {
          setImportWizardVisible(false);
          setImportWizardData(null);
          invalidate(); // Refresh the agent list
        }}
      />
    </div>
  );
}

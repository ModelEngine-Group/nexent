"use client";

import { Layout, Row, Col, Card } from "antd";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useSetupFlow } from "@/hooks/useSetupFlow";
import { useConfig } from "@/hooks/useConfig";
import { motion } from "framer-motion";
import AgentConfigComp from "./components/AgentConfigComp";
import AgentInfoComp from "./components/AgentInfoComp";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import AgentVersionManage from "./AgentVersionManage";
import AgentSelectorHeader from "./components/AgentSelectorHeader";
import { Nl2AgentChatPanel } from "../newchat/assistant-ui/nl2agent-chat-panel";
import type { Nl2AgentStateEvent } from "../newchat/adapter/remote-chat-model-adapter";
import { searchAgentInfo } from "@/services/agentConfigService";
import log from "@/lib/logger";
import { Nl2AgentFlowProvider, useNl2AgentFlow } from "@/contexts/nl2AgentFlow";

const { Header, Content } = Layout;

function AgentSetupOrchestratorContent() {
  const { pageVariants, pageTransition } = useSetupFlow();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const { markDraftCreated, resetFlow, sessionGeneration } = useNl2AgentFlow();
  const enterCreateMode = useAgentConfigStore((state) => state.enterCreateMode);
  const reset = useAgentConfigStore((state) => state.reset);
  const setDefaultLlmConfig = useAgentConfigStore(
    (state) => state.setDefaultLlmConfig
  );
  const setCurrentAgent = useAgentConfigStore((state) => state.setCurrentAgent);
  const isAgentReadOnly = useAgentConfigStore((state) => state.isReadOnly());
  const { config } = useConfig();
  const initializedRef = useRef(false);

  // Sync default LLM config from load_config
  useEffect(() => {
    if (config?.models?.llm) {
      setDefaultLlmConfig({
        id: config.models.llm.id || 0,
        name: config.models.llm.modelName || "",
        displayName: config.models.llm.displayName || "",
      });
    }
  }, [config, setDefaultLlmConfig]);

  // Local UI state for version panel
  const [isShowVersionManagePanel, setIsShowVersionManagePanel] =
    useState(false);

  // Initialize exactly once. A valid deep link wins; every other /agents entry
  // starts in create mode so the default NL2Agent panel is immediately usable.
  useEffect(() => {
    if (initializedRef.current) return;
    initializedRef.current = true;
    const agentId = searchParams.get("agent_id");
    const numericAgentId = Number(agentId);
    if (!agentId || !Number.isInteger(numericAgentId) || numericAgentId <= 0) {
      enterCreateMode();
      return;
    }

    let isRequestActive = true;
    const loadAgent = async () => {
      try {
        const result = await searchAgentInfo(numericAgentId);
        if (!isRequestActive) return;
        if (result.success && result.data) {
          setCurrentAgent(result.data);
        } else {
          log.warn("Failed to load agent from URL agent_id:", result.message);
          enterCreateMode();
        }
      } catch (error) {
        if (isRequestActive) {
          log.error("Failed to load agent from URL agent_id:", error);
          enterCreateMode();
        }
      }
    };
    loadAgent();

    return () => {
      isRequestActive = false;
    };
  }, [enterCreateMode, searchParams, setCurrentAgent]);

  const handleAgentContextChange = useCallback(
    (agentId: number | null) => {
      resetFlow(agentId);
      setIsShowVersionManagePanel(false);
    },
    [resetFlow]
  );

  const handleDraftCreated = useCallback(
    async (event: Nl2AgentStateEvent) => {
      const agentId = event.agent_id;
      markDraftCreated(agentId);
      try {
        const result = await searchAgentInfo(agentId);
        if (!result.success || !result.data) {
          log.error("Failed to synchronize NL2Agent draft:", result.message);
          return;
        }
        setCurrentAgent(result.data);
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ["agents"] }),
          queryClient.invalidateQueries({ queryKey: ["agentInfo"] }),
          queryClient.invalidateQueries({ queryKey: ["tools"] }),
          queryClient.invalidateQueries({ queryKey: ["skills"] }),
        ]);
      } catch (error) {
        log.error("Failed to synchronize NL2Agent draft:", error);
      }
    },
    [markDraftCreated, queryClient, setCurrentAgent]
  );

  const handleResourcesBound = useCallback(
    async (agentId: number): Promise<boolean> => {
      try {
        const result = await searchAgentInfo(agentId);
        if (!result.success || !result.data) {
          log.error(
            "Failed to synchronize NL2Agent resource bindings:",
            result.message
          );
          return false;
        }
        setCurrentAgent(result.data);
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ["agents"] }),
          queryClient.invalidateQueries({ queryKey: ["agentInfo"] }),
          queryClient.invalidateQueries({ queryKey: ["tools"] }),
          queryClient.invalidateQueries({ queryKey: ["skills"] }),
          queryClient.invalidateQueries({ queryKey: ["toolInfo"] }),
        ]);
        return true;
      } catch (error) {
        log.error("Failed to synchronize NL2Agent resource bindings:", error);
        return false;
      }
    },
    [queryClient, setCurrentAgent]
  );

  // Reset agent selection state when leaving the page
  useEffect(() => {
    return () => {
      reset();
    };
  }, [reset]);

  const headerStyle: React.CSSProperties = {
    padding: 0,
    minHeight: 120,
    height: "auto",
    lineHeight: "normal",
    background: "#fff",
    flexShrink: 0,
  };

  const contentStyle: React.CSSProperties = {
    padding: "32px",
    background: "#fff",
    overflow: "auto",
    flex: 1,
    minHeight: 0,
  };

  return (
    <div className="w-full h-full">
      <Layout
        className="h-full bg-white"
        style={{
          borderRadius: 8,
          border: "1px solid #f0f0f0",
          display: "flex",
          flexDirection: "column",
        }}
      >
        {/* Fixed Header */}
        <Header style={headerStyle}>
          <AgentSelectorHeader
            onOpenVersionManage={() => setIsShowVersionManagePanel(true)}
            isShowVersionManagePanel={isShowVersionManagePanel}
            onCloseVersionManagePanel={() => setIsShowVersionManagePanel(false)}
            onAgentContextChange={handleAgentContextChange}
          />
        </Header>
        <motion.div
          initial="initial"
          animate="in"
          exit="out"
          variants={pageVariants}
          transition={pageTransition}
          style={{ width: "100%", flex: 1, minHeight: 0, display: "flex" }}
        >
          <Content style={contentStyle}>
            <div
              className="h-full"
              style={{
                display: "flex",
                gap: isShowVersionManagePanel ? 18 : 0,
                width: "100%",
                height: "100%",
              }}
            >
              {/* Main content area with two columns */}
              <div
                style={{
                  flex: isShowVersionManagePanel ? 1 : "none",
                  width: isShowVersionManagePanel ? "auto" : "100%",
                  height: "100%",
                }}
              >
                <Row
                  gutter={{ lg: 32, md: 32, sm: 16 }}
                  className="h-full px-4"
                  align="stretch"
                  style={{ height: "100%" }}
                >
                  <Col
                    xs={24}
                    sm={24}
                    md={24}
                    lg={8}
                    className="flex flex-col h-full"
                  >
                    <Card
                      className="h-full"
                      styles={{
                        body: {
                          height: "100%",
                          padding: 0,
                          overflow: "hidden",
                        },
                      }}
                    >
                      <Nl2AgentChatPanel
                        key={sessionGeneration}
                        disabled={isAgentReadOnly}
                        onStateEvent={handleDraftCreated}
                        onResourcesBound={handleResourcesBound}
                      />
                    </Card>
                  </Col>
                  {/* Middle column: Agent Config */}
                  <Col
                    xs={24}
                    sm={24}
                    md={24}
                    lg={8}
                    className="flex flex-col h-full"
                  >
                    <Card
                      className="h-full"
                      styles={{ body: { height: "100%" } }}
                    >
                      <AgentConfigComp />
                    </Card>
                  </Col>
                  {/* Right column: Agent Info */}
                  <Col
                    xs={24}
                    sm={24}
                    md={24}
                    lg={8}
                    className="flex flex-col h-full"
                  >
                    <Card
                      className="h-full"
                      styles={{ body: { height: "100%" } }}
                    >
                      <AgentInfoComp />
                    </Card>
                  </Col>
                </Row>
              </div>

              {/* Version Management Panel - Fixed width */}
              {isShowVersionManagePanel && (
                <motion.div
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: 20 }}
                  transition={{ duration: 0.2 }}
                  style={{ width: 360, height: "100%", flexShrink: 0 }}
                >
                  <AgentVersionManage />
                </motion.div>
              )}
            </div>
          </Content>
        </motion.div>
      </Layout>
    </div>
  );
}

export default function AgentSetupOrchestrator() {
  return (
    <Nl2AgentFlowProvider>
      <AgentSetupOrchestratorContent />
    </Nl2AgentFlowProvider>
  );
}

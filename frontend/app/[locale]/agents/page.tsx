"use client";

import { Alert, App, Layout, Row, Col, Card, Spin } from "antd";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useSetupFlow } from "@/hooks/useSetupFlow";
import { useConfig } from "@/hooks/useConfig";
import { motion } from "framer-motion";
import AgentConfigComp from "./components/AgentConfigComp";
import AgentInfoComp from "./components/AgentInfoComp";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import AgentVersionManage from "./AgentVersionManage";
import AgentSelectorHeader from "./components/AgentSelectorHeader";
import { searchAgentInfo } from "@/services/agentConfigService";
import log from "@/lib/logger";
import { Nl2AgentEmbeddedChat } from "@/components/nl2agent/Nl2AgentEmbeddedChat";
import {
  resolveNl2AgentSessionByAgent,
  startNl2AgentSession,
  type Nl2AgentSessionSummary,
} from "@/services/nl2agentService";

const { Header, Content } = Layout;

export default function AgentSetupOrchestrator() {
  const { pageVariants, pageTransition } = useSetupFlow();
  const searchParams = useSearchParams();
  const router = useRouter();
  const params = useParams<{ locale: string }>();
  const locale = params.locale || "en";
  const queryClient = useQueryClient();
  const { message } = App.useApp();
  const enterCreateMode = useAgentConfigStore((state) => state.enterCreateMode);
  const reset = useAgentConfigStore((state) => state.reset);
  const setDefaultLlmConfig = useAgentConfigStore(
    (state) => state.setDefaultLlmConfig
  );
  const currentAgentId = useAgentConfigStore((state) => state.currentAgentId);
  const setCurrentAgent = useAgentConfigStore((state) => state.setCurrentAgent);
  const { config } = useConfig();

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
  const [nl2AgentSession, setNl2AgentSession] =
    useState<Nl2AgentSessionSummary | null>(null);
  const [nl2AgentLoading, setNl2AgentLoading] = useState(false);

  // Handle auto-create mode from URL params
  useEffect(() => {
    const create = searchParams?.get("create");
    if (create === "true") {
      setTimeout(() => {
        enterCreateMode();
      }, 100);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enterCreateMode]);

  // Handle auto-select agent from URL params (agent_id)
  useEffect(() => {
    const agentId = searchParams.get("agent_id");
    if (agentId && (!currentAgentId || String(currentAgentId) !== agentId)) {
      const loadAgent = async () => {
        try {
          const result = await searchAgentInfo(parseInt(agentId));
          if (result.success && result.data) {
            setCurrentAgent(result.data);
          } else {
            log.warn("Failed to load agent from URL agent_id:", result.message);
          }
        } catch (error) {
          log.error("Failed to load agent from URL agent_id:", error);
        }
      };
      loadAgent();
    }
  }, [searchParams, currentAgentId, setCurrentAgent]);

  useEffect(() => {
    if (!currentAgentId) {
      setNl2AgentSession(null);
      return;
    }
    let cancelled = false;
    void resolveNl2AgentSessionByAgent(Number(currentAgentId))
      .then((session) => {
        if (!cancelled) setNl2AgentSession(session);
      })
      .catch((error) => {
        log.error("Failed to restore NL2AGENT session:", error);
        if (!cancelled) setNl2AgentSession(null);
      });
    return () => {
      cancelled = true;
    };
  }, [currentAgentId]);

  const refreshGeneratedAgent = useCallback(async () => {
    if (!nl2AgentSession) return;
    const [agentResult, session] = await Promise.all([
      searchAgentInfo(nl2AgentSession.draft_agent_id),
      resolveNl2AgentSessionByAgent(nl2AgentSession.draft_agent_id),
    ]);
    if (agentResult.success && agentResult.data) {
      setCurrentAgent(agentResult.data);
    }
    if (session) setNl2AgentSession(session);
    await queryClient.invalidateQueries({ queryKey: ["agents"] });
  }, [nl2AgentSession, queryClient, setCurrentAgent]);

  const handleStartAgentBuilder = useCallback(async () => {
    if (nl2AgentLoading || nl2AgentSession?.status === "active") return;
    setNl2AgentLoading(true);
    try {
      const started = await startNl2AgentSession();
      const result = await searchAgentInfo(started.draft_agent_id);
      if (!result.success || !result.data) {
        throw new Error(result.message || "Failed to load generated agent.");
      }
      setCurrentAgent(result.data);
      setNl2AgentSession({
        conversation_id: started.conversation_id,
        draft_agent_id: started.draft_agent_id,
        nl2agent_agent_id: started.nl2agent_agent_id,
        status: "active",
      });
      setIsShowVersionManagePanel(false);
      router.replace(`/${locale}/agents?agent_id=${started.draft_agent_id}`);
      await queryClient.invalidateQueries({ queryKey: ["agents"] });
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : "Failed to start Agent Builder."
      );
    } finally {
      setNl2AgentLoading(false);
    }
  }, [
    locale,
    message,
    nl2AgentLoading,
    nl2AgentSession?.status,
    queryClient,
    router,
    setCurrentAgent,
  ]);

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
            onStartAgentBuilder={() => void handleStartAgentBuilder()}
            agentBuilderActive={
              nl2AgentSession?.status === "active" || nl2AgentLoading
            }
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
              {/* Main content area: assistant plus the original two configuration columns. */}
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
                  {nl2AgentSession && (
                    <Col
                      xs={24}
                      sm={24}
                      md={24}
                      lg={8}
                      className="flex flex-col h-full"
                    >
                      <Card
                        className="h-full overflow-hidden"
                        styles={{ body: { height: "100%", padding: 0 } }}
                      >
                        {nl2AgentLoading ? (
                          <div className="flex h-full items-center justify-center">
                            <Spin />
                          </div>
                        ) : (
                          <Nl2AgentEmbeddedChat
                            key={nl2AgentSession.conversation_id}
                            session={nl2AgentSession}
                            onSessionResumed={setNl2AgentSession}
                            onStateChanged={() => void refreshGeneratedAgent()}
                          />
                        )}
                      </Card>
                    </Col>
                  )}
                  {/* Left column: Agent Config */}
                  <Col
                    xs={24}
                    sm={24}
                    md={24}
                    lg={nl2AgentSession ? 8 : 12}
                    className="flex flex-col h-full"
                  >
                    <Card
                      className="h-full"
                      styles={{ body: { height: "100%" } }}
                    >
                      {nl2AgentSession?.status === "active" && (
                        <Alert
                          className="mb-3"
                          type="info"
                          showIcon
                          title="配置由智能体生成助手实时维护，完成应用后可手动编辑。"
                        />
                      )}
                      <div
                        className={
                          nl2AgentSession?.status === "active"
                            ? "pointer-events-none opacity-70"
                            : undefined
                        }
                        aria-disabled={nl2AgentSession?.status === "active"}
                      >
                        <AgentConfigComp />
                      </div>
                    </Card>
                  </Col>
                  {/* Right column: Agent Info */}
                  <Col
                    xs={24}
                    sm={24}
                    md={24}
                    lg={nl2AgentSession ? 8 : 12}
                    className="flex flex-col h-full"
                  >
                    <Card
                      className="h-full"
                      styles={{ body: { height: "100%" } }}
                    >
                      <div
                        className={
                          nl2AgentSession?.status === "active"
                            ? "pointer-events-none opacity-70"
                            : undefined
                        }
                        aria-disabled={nl2AgentSession?.status === "active"}
                      >
                        <AgentInfoComp />
                      </div>
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

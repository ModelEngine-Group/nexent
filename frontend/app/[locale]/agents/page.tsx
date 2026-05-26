"use client";

import { Layout, Row, Col, Card } from "antd";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { useSetupFlow } from "@/hooks/useSetupFlow";
import { useConfig } from "@/hooks/useConfig";
import { motion } from "framer-motion";
import AgentConfigComp from "./components/AgentConfigComp";
import AgentInfoComp from "./components/AgentInfoComp";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import AgentVersionManage from "./AgentVersionManage";
import AgentSelectorHeader from "./components/AgentSelectorHeader";

const { Header, Content } = Layout;

export default function AgentSetupOrchestrator() {
  const { pageVariants, pageTransition } = useSetupFlow();
  const searchParams = useSearchParams();
  const enterCreateMode = useAgentConfigStore((state) => state.enterCreateMode);
  const reset = useAgentConfigStore((state) => state.reset);
  const setDefaultLlmConfig = useAgentConfigStore((state) => state.setDefaultLlmConfig);
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
  const [isShowVersionManagePanel, setIsShowVersionManagePanel] = useState(false);

  // Handle auto-create mode from URL params
  useEffect(() => {
    const create = searchParams.get('create');
    if (create === 'true') {
      setTimeout(() => {
        enterCreateMode();
      }, 100);
    }
  }, [searchParams, enterCreateMode]);

  // Reset agent selection state when leaving the page
  useEffect(() => {
    return () => {
      reset();
    };
  }, [reset]);

  const headerStyle: React.CSSProperties = {
    padding: 0,
    height: 120,
    lineHeight: '120px',
    background: '#fff',
    flexShrink: 0,
  };

  const contentStyle: React.CSSProperties = {
    padding: '32px',
    background: '#fff',
    overflow: 'auto',
    flex: 1,
    minHeight: 0,
  };

  return (
    <div className="w-full h-full">
      <Layout className="h-full bg-white" style={{ borderRadius: 8, border: '1px solid #f0f0f0', display: 'flex', flexDirection: 'column' }}>
        {/* Fixed Header */}
        <Header style={headerStyle}>
          <AgentSelectorHeader
            onOpenVersionManage={() => setIsShowVersionManagePanel(true)}
            isShowVersionManagePanel={isShowVersionManagePanel}
            onCloseVersionManagePanel={() => setIsShowVersionManagePanel(false)}
          />
        </Header>
        <motion.div
          initial="initial"
          animate="in"
          exit="out"
          variants={pageVariants}
          transition={pageTransition}
          style={{ width: "100%", flex: 1, minHeight: 0, display: 'flex' }}
        >
          <Content style={contentStyle}>
            <div
              className="h-full"
              style={{
                display: 'flex',
                gap: isShowVersionManagePanel ? 18 : 0,
                width: '100%',
                height: '100%',
              }}
            >
              {/* Main content area with two columns */}
              <div
                style={{
                  flex: isShowVersionManagePanel ? 1 : 'none',
                  width: isShowVersionManagePanel ? 'auto' : '100%',
                  height: '100%',
                }}
              >
                <Row
                  gutter={{ lg: 32, md: 32, sm: 16 }}
                  className="h-full px-4"
                  align="stretch"
                  style={{ height: '100%' }}
                >
                  {/* Left column: Agent Config */}
                  <Col
                    xs={24}
                    sm={24}
                    md={24}
                    lg={12}
                    className="flex flex-col h-full"
                  >
                    <Card className="h-full" styles={{ body: { height: '100%' } }}>
                      <AgentConfigComp />
                    </Card>
                  </Col>
                  {/* Right column: Agent Info */}
                  <Col
                    xs={24}
                    sm={24}
                    md={24}
                    lg={12}
                    className="flex flex-col h-full"
                  >
                    <Card className="h-full" styles={{ body: { height: '100%' } }}>
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

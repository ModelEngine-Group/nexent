"use client";

import { Card, Row, Col, Flex, Button } from "antd";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";


import { useSetupFlow } from "@/hooks/useSetupFlow";
import { motion } from "framer-motion";
import AgentManageComp from "./components/AgentManageComp";
import AgentConfigComp from "./components/AgentConfigComp";
import AgentInfoComp from "./components/AgentInfoComp";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import AgentVersionManage from "./AgentVersionManage";

export default function AgentSetupOrchestrator() {
  const { pageVariants, pageTransition } = useSetupFlow();
  const searchParams = useSearchParams();
  const enterCreateMode = useAgentConfigStore((state) => state.enterCreateMode);

  // Local UI state for version panel
  const [isShowVersionManagePanel, setIsShowVersionManagePanel] = useState(false);

  // Handle auto-create mode from URL params
  useEffect(() => {
    const create = searchParams.get('create');
    if (create === 'true') {
      // Small delay to ensure component is fully mounted
      setTimeout(() => {
        enterCreateMode();
      }, 100);
    }
  }, [searchParams, enterCreateMode]);

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
        {/* Main content area with adaptive width */}
        <Flex className="h-full w-full" gap={16}>
          <Card
            className="h-full min-h-0 flex-1"
            style={{ minHeight: 400, overflow: "hidden" }}
          >
            <style jsx global>{`
              .ant-card-body {
                height: 100%;
              }
            `}</style>
            {/* Three-column layout using Ant Design Grid */}
            <Row
              gutter={[16, 16]}
              className="h-full min-h-0 w-full"
              align="stretch"
            >
              {/* Left column: Agent Management */}
              <Col
                xs={24}
                sm={24}
                md={24}
                lg={8}
                className="flex flex-col h-full w-full"
              >
                <AgentManageComp />
              </Col>

              {/* Middle column: Agent Config */}
              <Col
                xs={24}
                sm={24}
                md={24}
                lg={8}
                className="flex flex-col h-full w-full"
              >
                <AgentConfigComp />
              </Col>

              {/* Right column: Agent Info */}
              <Col
                xs={24}
                sm={24}
                md={24}
                lg={8}
                className="flex flex-col h-full w-full"
              >
                <AgentInfoComp
                  isShowVersionManagePanel={isShowVersionManagePanel}
                  openVersionManagePanel={() => setIsShowVersionManagePanel(true)}
                  closeVersionManagementPanel={() => setIsShowVersionManagePanel(false)}
                />
              </Col>
            </Row>
          </Card>

          {/* Version Management Panel - Fixed width */}
          {isShowVersionManagePanel && (
            <motion.div
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 20 }}
              transition={{ duration: 0.2 }}
              style={{ width: 400, height: "100%", flexShrink: 0 }}
            >
              <AgentVersionManage />
            </motion.div>
          )}
        </Flex>
      </motion.div>
    </div>
  )
}

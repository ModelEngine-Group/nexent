"use client";

import { Card, Row, Col, Flex } from "antd";
import { useSearchParams } from "next/navigation";
import { useEffect } from "react";

import { useSetupFlow } from "@/hooks/useSetupFlow";
import { motion } from "framer-motion";
import AgentManageComp from "./components/AgentManageComp";
import AgentConfigComp from "./components/AgentConfigComp";
import AgentInfoComp from "./components/AgentInfoComp";
import { useAgentConfigStore } from "@/stores/agentConfigStore";

export default function AgentSetupOrchestrator() {
  const { pageVariants, pageTransition } = useSetupFlow();
  const searchParams = useSearchParams();
  const enterCreateMode = useAgentConfigStore((state) => state.enterCreateMode);

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
    <Flex
      justify="center"
      align="center"
      className="py-8 px-16 h-full w-full"
    >
      <motion.div
        initial="initial"
        animate="in"
        exit="out"
        variants={pageVariants}
        transition={pageTransition}
        style={{ width: "100%", height: "100%" }}
      >
        <Card
          className="h-full min-h-0 w-full min-w-0"
          style={{ minHeight: 400, maxHeight: "80vh" }}
        >
          <style jsx global>{`
            .ant-card-body {
              height: 100%;
            }
          `}</style>
          {/* Three-column layout using Ant Design Grid */}
          <Row
            gutter={[16, 16]}
            className="h-full min-h-0 w-full min-w-0"
            align="stretch"
          >
            {/* Left column: Agent Management */}
            <Col
              xs={24}
              sm={24}
              md={24}
              lg={24}
              xl={8}
              className="flex flex-col h-full w-full"
            >
              <AgentManageComp />
            </Col>

            {/* Middle column: Agent Config */}
            <Col
              xs={24}
              sm={24}
              md={24}
              lg={24}
              xl={8}
              className="flex flex-col h-full w-full"
            >
              <AgentConfigComp />
            </Col>

            {/* Right column: Agent Info */}
            <Col
              xs={24}
              sm={24}
              md={24}
              lg={24}
              xl={8}
              className="flex flex-col h-full w-full"
            >
              <AgentInfoComp />
            </Col>
          </Row>
        </Card>
      </motion.div>
    </Flex>
  );
}

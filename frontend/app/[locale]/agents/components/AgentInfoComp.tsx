"use client";

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Row, Col, Flex, Badge, Divider, Button, Drawer, App } from "antd";
import { Bug, Save, Info } from "lucide-react";

import { AGENT_SETUP_LAYOUT_DEFAULT } from "@/const/agentConfig";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { useSaveGuard } from "@/hooks/agent/useSaveGuard";
import { AgentBusinessInfo, AgentProfileInfo } from "@/types/agentConfig";

import AgentGenerateDetail from "./agentInfo/AgentGenerateDetail";
import DebugConfig from "./agentInfo/DebugConfig";

export interface AgentInfoCompProps {}

export default function AgentInfoComp({}: AgentInfoCompProps) {
  const { t } = useTranslation("common");

  // Get data from store
  const { editedAgent, updateBusinessInfo, updateProfileInfo, isCreatingMode } =
    useAgentConfigStore();

  // Get state from store
  const currentAgentId = useAgentConfigStore((state) => state.currentAgentId);

  const editable = !!(currentAgentId || isCreatingMode);

  // Save guard hook
  const saveGuard = useSaveGuard();

  // Debug drawer state
  const [isDebugDrawerOpen, setIsDebugDrawerOpen] = useState(false);

  // Handle business info updates
  const handleUpdateBusinessInfo = (updates: AgentBusinessInfo) => {
    updateBusinessInfo(updates);
  };

  // Handle profile info updates
  const handleUpdateProfile = (updates: AgentProfileInfo) => {
    updateProfileInfo(updates);
  };

  return (
    <>
      {
        <Flex vertical className="h-full overflow-hidden">
          <Row>
            <Col>
              <Flex
                justify="flex-start"
                align="center"
                gap={8}
                style={{ marginBottom: "4px" }}
              >
                <Badge count={1} color="blue" />
                <h2 className="text-lg font-medium">
                  {t("guide.steps.describeBusinessLogic.title")}
                </h2>
              </Flex>
            </Col>
          </Row>

          <Divider style={{ margin: "10px 0" }} />

          <Row className="flex-1 min-h-0 h-full">
            <Col xs={24} className="h-full">
              <Flex vertical className="h-full min-h-0 w-full min-w-0">
                <AgentGenerateDetail
                  editable={editable}
                  editedAgent={editedAgent}
                  currentAgentId={currentAgentId}
                  onUpdateProfile={handleUpdateProfile}
                  onUpdateBusinessInfo={handleUpdateBusinessInfo}
                />
              </Flex>
            </Col>
          </Row>

          <Row className="justify-evenly align-center mt-3">
            <Col className="flex gap-4">
              <Button
                type="primary"
                icon={<Bug size={16} />}
                onClick={() =>
                  saveGuard.saveWithModal().then((success) => {
                    if (success) {
                      setIsDebugDrawerOpen(true);
                    }
                  })
                }
                size="middle"
              >
                {t("systemPrompt.button.debug")}
              </Button>

              <Button
                type="primary"
                className="responsive-button bg-green-500 hover:bg-green-600 border-green-500 hover:border-green-600"
                icon={<Save size={16} />}
                onClick={saveGuard.save}
                size="middle"
                title={t("common.save")}
              >
                {t("common.save")}
              </Button>
            </Col>
          </Row>
        </Flex>
      }

      {!editable && (
        <Flex>
          <div className="absolute inset-0 bg-white bg-opacity-95 flex items-center justify-center z-50 transition-all duration-300 ease-out animate-in fade-in-0">
            <div className="space-y-3 animate-in fade-in-50 duration-400 delay-50 text-center">
              <div className="flex items-center justify-center gap-3 animate-in slide-in-from-bottom-2 duration-300 delay-150">
                <Info
                  className="text-gray-400 transition-all duration-300 animate-in zoom-in-75 delay-100"
                  size={48}
                />
                <h3 className="text-lg font-medium text-gray-700 transition-all duration-300">
                  {t("systemPrompt.nonEditing.title")}
                </h3>
              </div>
              <p className="text-sm text-gray-500 transition-all duration-300">
                {t("systemPrompt.nonEditing.subtitle")}
              </p>
            </div>
          </div>
        </Flex>
      )}

      {/* Debug drawer */}
      <Drawer
        title={t("agent.debug.title")}
        placement="right"
        onClose={() => setIsDebugDrawerOpen(false)}
        open={isDebugDrawerOpen}
        styles={{
          wrapper: {
            width: AGENT_SETUP_LAYOUT_DEFAULT.DRAWER_WIDTH,
          },
          body: {
            padding: 0,
            height: "100%",
            overflow: "hidden",
          },
        }}
      >
        <div className="h-full">
          <DebugConfig agentId={currentAgentId || 0} />
        </div>
      </Drawer>
    </>
  );
}

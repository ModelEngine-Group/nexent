"use client";

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Row, Col, Flex, Badge, Divider, Button, Drawer, Tooltip, Tag } from "antd";
import { useQueryClient } from "@tanstack/react-query";
import { Bug, Save, Info, GitBranch, History } from "lucide-react";

import { AGENT_SETUP_LAYOUT_DEFAULT } from "@/const/agentConfig";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { useSaveGuard } from "@/hooks/agent/useSaveGuard";
import { AgentBusinessInfo, AgentProfileInfo } from "@/types/agentConfig";

import AgentGenerateDetail from "./agentInfo/AgentGenerateDetail";
import DebugConfig from "./agentInfo/DebugConfig";
import { useAgentVersionList } from "@/hooks/agent/useAgentVersionList";
import { useAgentVersionDetail } from "@/hooks/agent/useAgentVersionDetail";
import { useAgentInfo } from "@/hooks/agent/useAgentInfo";

export interface AgentInfoCompProps {
  isShowVersionManagePanel: boolean;
  openVersionManagePanel: () => void;
  closeVersionManagementPanel: () => void;
}

export default function AgentInfoComp({
  isShowVersionManagePanel,
  openVersionManagePanel,
  closeVersionManagementPanel,
}: AgentInfoCompProps) {
  const { t } = useTranslation("common");

  // Get data from store
  const {
    editedAgent,
    updateBusinessInfo,
    updateProfileInfo,
    isCreatingMode,
    currentAgentPermission,
  } = useAgentConfigStore();

  const currentAgentId = useAgentConfigStore((state) => state.currentAgentId);

  const isPanelActive = (currentAgentId != null && currentAgentId != undefined) || isCreatingMode;
  const { agentVersionList, total } = useAgentVersionList(currentAgentId)

  const { agentInfo } = useAgentInfo(currentAgentId);

  const { agentVersionDetail } = useAgentVersionDetail(
    currentAgentId, agentInfo?.current_version_no
  );
    
  const isReadOnly = isPanelActive && !isCreatingMode && currentAgentPermission === "READ_ONLY";
  const isEditable = isPanelActive && !isReadOnly;

  // Save guard hook
  const saveGuard = useSaveGuard();

  // Debug drawer state
  const [isDebugDrawerOpen, setIsDebugDrawerOpen] = useState(false);

  // Generation state shared with AgentGenerateDetail
  const [isGenerating, setIsGenerating] = useState(false);

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
            <Col className="w-full">
              <Flex
                justify="space-between"
                align="center"
                gap={8}
                style={{ marginBottom: "4px" }}
                className="w-full"
              >
                <Flex justify="flex-start" align="center" gap={8}>
                  <Badge count={3} color="blue" />
                  <h2 className="text-lg font-medium">
                    {t("guide.steps.describeBusinessLogic.title")}
                  </h2>
                </Flex>
                <Button
                  icon={<GitBranch size={16} />}
                  onClick={isShowVersionManagePanel ? closeVersionManagementPanel : openVersionManagePanel}
                  type={isShowVersionManagePanel ? "primary" : "default"}
                >
                  {t("agent.version.manage")}
                </Button>
              </Flex>
            </Col>
          </Row>

          <Divider style={{ margin: "10px 0" }} />
          {!isCreatingMode && agentInfo?.current_version_no !== 0 && total > 0 && (
            <Row style={{ marginBottom: "8px" }}>
              <Col className="w-full">
                <Flex
                  justify="space-between"
                  align="center"
                  className="w-full py-2 px-4 bg-gray-100 rounded-lg text-gray-700"
                >
                  <Flex justify="start" align="center" gap={4}>
                    <History size={16} />
                    <span className="text-sm">
                      {t("agent.version.currentVersion")} :
                    </span>
                    <Tag color="cyan" variant="outlined" className="rounded-md font-mono text-sm"> {agentVersionDetail?.version.version_name}</Tag>
                  </Flex>
                  <Flex justify="end" align="center" gap={8} >
                    {t("agent.version.totalVersions", { count: total ?? 0 })}
                  </Flex>
                </Flex>
              </Col>
            </Row>
          )}

          <Row className="flex-1 min-h-0 h-full">
            <Col xs={24} className="h-full">
              <Flex vertical className="h-full min-h-0 w-full min-w-0">
                <AgentGenerateDetail
                  editable={isEditable}
                  editedAgent={editedAgent}
                  currentAgentId={currentAgentId}
                  onUpdateProfile={handleUpdateProfile}
                  onUpdateBusinessInfo={handleUpdateBusinessInfo}
                  isGenerating={isGenerating}
                  setIsGenerating={setIsGenerating}
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
                disabled={isGenerating}
              >
                {t("systemPrompt.button.debug")}
              </Button>

              <Tooltip title={isReadOnly ? t("agent.noEditPermission") : undefined}>
                <span>
                  <Button
                    icon={<Save size={16} />}
                    color="green"
                    variant="solid"
                    onClick={saveGuard.save}
                    size="middle"
                    title={t("common.save")}
                    disabled={isGenerating || isReadOnly}
                  >
                    {t("common.save")}
                  </Button>
                </span>
              </Tooltip>
            </Col>
          </Row>
        </Flex>
      }

      {!isPanelActive && (
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
          <DebugConfig agentId={currentAgentId} />
        </div>
      </Drawer>
    </>
  );
}

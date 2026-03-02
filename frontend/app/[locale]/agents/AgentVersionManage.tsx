"use client";
import { useState } from "react";
import { GitBranch, GitCompare, Rocket } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Card, Flex, Button, Tag, Empty, Spin, message } from "antd";
import { useAgentVersionList } from "@/hooks/agent/useAgentVersionList";
import { useAgentInfo } from "@/hooks/agent/useAgentInfo";
import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { VersionCardItem } from "./AgentVersionCard";
import log from "@/lib/logger";
import AgentVersionCompareModal from "./versions/AgentVersionCompareModal";
import { compareVersions, type VersionCompareResponse } from "@/services/agentVersionService";

export default function AgentVersionManage() {
  const { t } = useTranslation("common");
  const currentAgentId = useAgentConfigStore((state) => state.currentAgentId);

  const { agentVersionList, total, isLoading, invalidate: invalidateAgentVersionList } = useAgentVersionList(currentAgentId);
  const { agentInfo, invalidate: invalidateAgentInfo } = useAgentInfo(currentAgentId);
  
  const [compareModalOpen, setCompareModalOpen] = useState(false);
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareData, setCompareData] = useState<VersionCompareResponse | null>(null);
  const [selectedVersionA, setSelectedVersionA] = useState<number | null>(null);
  const [selectedVersionB, setSelectedVersionB] = useState<number | null>(null);


  const loadComparison = async (agentId: number, versionNoA: number, versionNoB: number) => {
    try {
      setCompareLoading(true);
      const result = await compareVersions(agentId, versionNoA, versionNoB);
      setCompareData(result);
    } catch (error) {
      log.error("Failed to compare versions:", error);
      message.error(t("agent.version.compareError"));
    } finally {
      setCompareLoading(false);
    }
  };

  const handleOpenCompareModal = async () => {
    if (!currentAgentId) {
      message.error(t("agent.error.agentNotFound"));
      return;
    }
    if (agentVersionList.length < 2) {
      message.warning(t("agent.version.needTwoVersions"));
      return;
    }

    // Use the last two versions by version_no as default comparison
    const sorted = [...agentVersionList].sort((a, b) => a.version_no - b.version_no);
    const defaultVersionA = sorted[sorted.length - 2]?.version_no;
    const defaultVersionB = sorted[sorted.length - 1]?.version_no;

    if (!defaultVersionA || !defaultVersionB) {
      message.warning(t("agent.version.needTwoVersions"));
      return;
    }

    setSelectedVersionA(defaultVersionA);
    setSelectedVersionB(defaultVersionB);
    setCompareModalOpen(true);
    await loadComparison(currentAgentId, defaultVersionA, defaultVersionB);
  };

  const handleChangeVersionA = async (value: number) => {
    setSelectedVersionA(value);
    if (!currentAgentId || !selectedVersionB) {
      return;
    }
    if (value === selectedVersionB) {
      message.warning(t("agent.version.selectDifferentVersions"));
      return;
    }
    await loadComparison(currentAgentId, value, selectedVersionB);
  };

  const handleChangeVersionB = async (value: number) => {
    setSelectedVersionB(value);
    if (!currentAgentId || !selectedVersionA) {
      return;
    }
    if (value === selectedVersionA) {
      message.warning(t("agent.version.selectDifferentVersions"));
      return;
    }
    await loadComparison(currentAgentId, selectedVersionA, value);
  };

  const footer = [
    <Flex
      align="center"
      justify="space-between"
      gap={8}
      className="pl-4"
      key="actions"
    >
      <Tag color="blue">
        {t("agent.version.totalVersions", { count: total })}
      </Tag>
      <Button
        type="text"
        icon={<GitCompare size={16} />}
        onClick={handleOpenCompareModal}
      >
        {t("agent.version.compare")}
      </Button>
    </Flex>,
  ];

  return (
    <>
      <Card
        className="h-full min-h-0"
        style={{ minHeight: 400, height: "100%" }}
        title={
          <Flex align="center" gap={8}>
            <GitBranch size={16} />
            {t("agent.version.manage")}
          </Flex>
        }
        actions={footer}
        styles={{
          body: {
            height: "calc(100% - 112px)",
            overflow: "auto",
          },
        }}
      >
        {/* Desktop: Timeline style version list */}
        <div className="w-full h-full">
          <Spin spinning={isLoading}>
            {agentVersionList.length === 0 ? (
              <Flex align="center" justify="center" className="h-full">
                <Empty />
              </Flex>
            ) : (
              <Flex vertical >
                {agentVersionList.map((version) => (
                  <VersionCardItem
                    key={version.version_no}
                    version={version}
                    agentId={currentAgentId || 0}
                    currentVersionNo={agentInfo?.current_version_no}
                  />
                ))}
              </Flex>
            )}
          </Spin>
        </div>
      </Card>

      <AgentVersionCompareModal
        open={compareModalOpen}
        loading={compareLoading}
        versionList={agentVersionList}
        currentVersionNo={agentInfo?.current_version_no}
        compareData={compareData}
        onCancel={() => setCompareModalOpen(false)}
        selectedVersionNoA={selectedVersionA}
        selectedVersionNoB={selectedVersionB}
        onChangeVersionA={handleChangeVersionA}
        onChangeVersionB={handleChangeVersionB}
      />
    </>
  );
}

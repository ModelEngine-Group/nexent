// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useState } from "react";
import { GitCompare } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button, Drawer, Empty, Flex, Spin, Tag, message } from "antd";
import { useAgentVersionList } from "@/hooks/agent/useAgentVersionList";
import { useAgentStore } from "@/stores/agentStore";
import { VersionCardItem } from "./versions/agent-version-card";
import log from "@/lib/logger";
import AgentVersionCompareModal from "./versions/AgentVersionCompareModal";
import {
  compareVersions,
  type VersionCompareResponse,
} from "@/services/agentVersionService";
import type { Agent } from "@/types/agentConfig";

interface AgentVersionManageProps {
  open: boolean;
  onClose: () => void;
  currentVersionNo?: number;
  onRefreshAgentInfo: () => Promise<Agent | null>;
}

export default function AgentVersionManage({
  open,
  onClose,
  currentVersionNo,
  onRefreshAgentInfo,
}: AgentVersionManageProps) {
  const { t } = useTranslation("common");
  const currentAgentId = useAgentStore((state) => state.currentAgentId);

  const { agentVersionList, total, isLoading } =
    useAgentVersionList(currentAgentId);

  const [compareModalOpen, setCompareModalOpen] = useState(false);
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareData, setCompareData] = useState<VersionCompareResponse | null>(
    null
  );
  const [selectedVersionA, setSelectedVersionA] = useState<number | null>(null);
  const [selectedVersionB, setSelectedVersionB] = useState<number | null>(null);

  const loadComparison = async (
    agentId: number,
    versionNoA: number,
    versionNoB: number
  ) => {
    try {
      setCompareLoading(true);
      setCompareData(null);
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
    const sorted = [...agentVersionList].sort(
      (a, b) => a.version_no - b.version_no
    );
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

  return (
    <Drawer
      title={t("agent.version.manage")}
      open={open}
      onClose={() => {
        setCompareModalOpen(false);
        onClose();
      }}
      placement="right"
      size="min(560px, 100vw)"
      closable={{ placement: "end" }}
      destroyOnHidden
      footer={
        <Flex align="center" justify="space-between" gap={8}>
          <Tag color="blue">
            {t("agent.version.totalVersions", { count: total })}
          </Tag>
          <Button
            icon={<GitCompare size={16} />}
            disabled={isLoading || compareLoading || agentVersionList.length < 2}
            onClick={handleOpenCompareModal}
          >
            {t("agent.version.compare")}
          </Button>
        </Flex>
      }
    >
      <Spin spinning={isLoading}>
        {agentVersionList.length ? (
          <div className="flex flex-col gap-2">
            {agentVersionList.map((version) => (
              <VersionCardItem
                key={version.version_no}
                version={version}
                agentId={currentAgentId ?? 0}
                currentVersionNo={currentVersionNo}
                onRefreshAgentInfo={onRefreshAgentInfo}
              />
            ))}
          </div>
        ) : (
          <Empty description={t("agent.version.noVersions")} />
        )}
      </Spin>
      <AgentVersionCompareModal
        open={open && compareModalOpen}
        loading={compareLoading}
        versionList={agentVersionList}
        currentVersionNo={currentVersionNo}
        compareData={compareData}
        onCancel={() => setCompareModalOpen(false)}
        agentId={currentAgentId ?? undefined}
        selectedVersionNoA={selectedVersionA}
        selectedVersionNoB={selectedVersionB}
        onChangeVersionA={handleChangeVersionA}
        onChangeVersionB={handleChangeVersionB}
      />
    </Drawer>
  );
}

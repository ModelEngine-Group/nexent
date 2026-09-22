"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { App, Button, Modal } from "antd";
import { ArrowLeft, GitBranch } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useAgentInfo } from "@/hooks/agent/useAgentInfo";
import { searchAgentInfo } from "@/services/agentConfigService";
import { useAgentStore } from "@/stores/agentStore";

import Agents from "./agents";
import AgentVersion from "./agent-version";

export default function AgentEditorPage() {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const router = useRouter();
  const { agentId } = useParams<{ agentId: string }>();
  const requestedAgentId = Number(agentId);
  const isValidAgentId =
    Number.isInteger(requestedAgentId) && requestedAgentId > 0;
  const currentAgentId = useAgentStore((state) => state.currentAgentId);
  const initialize = useAgentStore((state) => state.initialize);
  const reset = useAgentStore((state) => state.reset);
  const [isVersionManageOpen, setIsVersionManageOpen] = useState(false);
  const { agentInfo, refetch: refetchAgentInfo } = useAgentInfo(currentAgentId);

  useEffect(() => {
    if (!isValidAgentId) {
      router.replace("/agents");
      return;
    }
    if (currentAgentId === requestedAgentId) return;

    void (async () => {
      const result = await searchAgentInfo(requestedAgentId);
      if (!result.success || !result.data) {
        message.error(
          result.message || t("agentConfig.agents.detailsLoadFailed")
        );
        router.replace("/agents");
        return;
      }
      initialize(result.data);
    })();
  }, [
    currentAgentId,
    initialize,
    isValidAgentId,
    message,
    requestedAgentId,
    router,
    t,
  ]);

  if (!isValidAgentId) return null;

  return (
    <div className="flex h-full min-h-0 flex-col bg-white">
      <div className="flex shrink-0 items-center justify-between border-b border-gray-200 bg-white px-6 py-2">
        <Button
          icon={<ArrowLeft className="size-4" />}
          type="text"
          onClick={() => {
            reset();
            router.push("/agents");
          }}
        >
          {t("common.back")}
        </Button>
        <Button
          icon={<GitBranch className="size-4" />}
          onClick={() => setIsVersionManageOpen(true)}
        >
          {t("agent.version.manage")}
        </Button>
      </div>
      <div className="min-h-0 flex-1">
        <Agents />
      </div>
      <Modal
        centered
        width={900}
        open={isVersionManageOpen}
        title={t("agent.version.manage")}
        onCancel={() => setIsVersionManageOpen(false)}
        footer={null}
      >
        <AgentVersion
          currentVersionNo={agentInfo?.current_version_no}
          onRefreshAgentInfo={refetchAgentInfo}
        />
      </Modal>
    </div>
  );
}

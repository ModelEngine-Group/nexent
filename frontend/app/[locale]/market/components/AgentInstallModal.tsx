"use client";

import React from "react";
import { MarketAgentDetail } from "@/types/market";
import { ImportAgentData } from "@/hooks/useAgentImport";
import AgentImportWizard from "@/components/agent/AgentImportWizard";

interface AgentInstallModalProps {
  visible: boolean;
  onCancel: () => void;
  agentDetails: MarketAgentDetail | null;
  onInstallComplete?: () => void;
}

export default function AgentInstallModal({
  visible,
  onCancel,
  agentDetails,
  onInstallComplete,
}: AgentInstallModalProps) {
  // Convert MarketAgentDetail to ImportAgentData format
  const importData: ImportAgentData | null = agentDetails?.agent_json
    ? {
        agent_id: agentDetails.agent_id,
        agent_info: agentDetails.agent_json.agent_info,
        mcp_info: agentDetails.agent_json.mcp_info,
      }
    : null;

  return (
    <AgentImportWizard
      visible={visible}
      onCancel={onCancel}
      initialData={importData}
      onImportComplete={onInstallComplete}
      title={undefined} // Use default title
      agentDisplayName={agentDetails?.display_name}
      agentDescription={agentDetails?.description}
    />
  );
}

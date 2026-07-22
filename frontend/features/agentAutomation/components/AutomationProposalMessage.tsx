"use client";

import { useEffect, useState } from "react";
import { message } from "antd";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";

import { agentAutomationService } from "@/services/agentAutomationService";
import { getAutomationErrorMessage } from "../errorMessage";
import type {
  AgentAutomationProposalData,
  UpdateAutomationProposalPayload,
} from "@/types/agentAutomation";
import AutomationProposalCard from "./AutomationProposalCard";
import AutomationProposalEditor from "./AutomationProposalEditor";

interface AutomationProposalMessageProps {
  proposal: AgentAutomationProposalData;
  readOnly?: boolean;
}

export default function AutomationProposalMessage({
  proposal,
  readOnly = false,
}: AutomationProposalMessageProps) {
  const { t, i18n } = useTranslation("common");
  const router = useRouter();
  const [currentProposal, setCurrentProposal] = useState(proposal);
  const [editorOpen, setEditorOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    setCurrentProposal(proposal);
  }, [proposal]);

  const handleSave = async (payload: UpdateAutomationProposalPayload) => {
    if (!currentProposal.proposal_id || readOnly) return;
    setSaving(true);
    try {
      const updated = await agentAutomationService.updateProposal(
        currentProposal.proposal_id,
        payload
      );
      setCurrentProposal(updated);
      setEditorOpen(false);
      message.success(t("agentAutomation.proposal.updated"));
    } catch (error) {
      message.error(
        getAutomationErrorMessage(
          error,
          t,
          "agentAutomation.proposal.updateFailed"
        )
      );
    } finally {
      setSaving(false);
    }
  };

  const handleConfirm = async () => {
    if (!currentProposal.proposal_id || readOnly) return;
    setConfirming(true);
    try {
      const task = await agentAutomationService.confirmProposal(
        currentProposal.proposal_id
      );
      setCurrentProposal({
        ...currentProposal,
        confirmed_task_id: task.task_id,
      });
      window.dispatchEvent(new Event("automationListUpdated"));
      message.success(t("agentAutomation.proposal.created"));
    } catch (error) {
      message.error(
        getAutomationErrorMessage(
          error,
          t,
          "agentAutomation.proposal.createFailed"
        )
      );
    } finally {
      setConfirming(false);
    }
  };

  const configureAgent = () => {
    const agentId = currentProposal.task?.agent_id;
    const suffix = agentId ? `?agent_id=${agentId}` : "";
    router.push(`/${i18n.language}/agents${suffix}`);
  };

  return (
    <>
      <AutomationProposalCard
        proposal={currentProposal}
        confirming={confirming}
        onConfirm={readOnly ? undefined : handleConfirm}
        onEdit={
          readOnly || currentProposal.ui_state === "PREPARING"
            ? undefined
            : () => setEditorOpen(true)
        }
        onConfigureAgent={readOnly ? undefined : configureAgent}
      />
      {currentProposal.task?.schedule_trigger && (
        <AutomationProposalEditor
          proposal={currentProposal}
          open={editorOpen}
          saving={saving}
          onCancel={() => setEditorOpen(false)}
          onSave={handleSave}
        />
      )}
    </>
  );
}

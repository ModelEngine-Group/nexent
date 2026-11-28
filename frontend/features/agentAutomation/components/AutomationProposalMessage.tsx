// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useState } from "react";
import { message } from "antd";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";

import { agentAutomationService } from "@/services/agentAutomationService";
import { getAutomationErrorMessage } from "../errorMessage";
import {
  AUTOMATION_CONFIRMED_EVENT,
  AUTOMATION_LIST_UPDATED_EVENT,
  type AutomationConfirmation,
} from "../confirmationEvent";
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
  const [editedProposal, setEditedProposal] = useState<{
    source: AgentAutomationProposalData;
    value: AgentAutomationProposalData;
  }>();
  const [receipt, setReceipt] = useState<AutomationConfirmation>();
  const [editorOpen, setEditorOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const currentDraft =
    editedProposal?.source === proposal ? editedProposal.value : proposal;
  const currentProposal =
    receipt && receipt.proposal_id === proposal.proposal_id
      ? { ...currentDraft, confirmed_task_id: receipt.task_id }
      : currentDraft;

  useEffect(() => {
    if (readOnly) return;
    const onConfirmed = (event: Event) => {
      const confirmation = (event as CustomEvent<AutomationConfirmation>)
        .detail;
      if (confirmation && confirmation.proposal_id === proposal.proposal_id) {
        setReceipt(confirmation);
      }
    };
    window.addEventListener(AUTOMATION_CONFIRMED_EVENT, onConfirmed);
    return () =>
      window.removeEventListener(AUTOMATION_CONFIRMED_EVENT, onConfirmed);
  }, [proposal.proposal_id, readOnly]);

  const handleSave = async (payload: UpdateAutomationProposalPayload) => {
    if (!currentProposal.proposal_id || readOnly) return;
    setSaving(true);
    try {
      const updated = await agentAutomationService.updateProposal(
        currentProposal.proposal_id,
        payload
      );
      setEditedProposal({ source: proposal, value: updated });
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
      setReceipt({
        proposal_id: currentProposal.proposal_id,
        task_id: task.task_id,
      });
      window.dispatchEvent(new Event(AUTOMATION_LIST_UPDATED_EVENT));
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
    router.push(
      agentId
        ? `/${i18n.language}/agents/${agentId}`
        : `/${i18n.language}/agents`
    );
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

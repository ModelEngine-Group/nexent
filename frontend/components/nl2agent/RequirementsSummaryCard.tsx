"use client";

import React, { useCallback, useMemo, useState } from "react";
import { Alert, Button, Spin } from "antd";
import { CheckCircle2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { Nl2AgentRequirementsSummary } from "@/services/nl2agentService";
import { ActionCard, StaticFieldList } from "./ActionCard";
import {
  toRequirementsSummaryRequest,
  type RequirementsSummaryCardPayload,
} from "./cardPayloadTypes";
import { useNl2AgentCardLifecycle } from "./useNl2AgentCardLifecycle";
import { useNl2AgentWorkflow } from "./Nl2AgentWorkflowContext";

export interface RequirementsSummaryCardProps {
  agentId: number;
  summary: RequirementsSummaryCardPayload;
  workflowRevision?: number;
}

const labels: Array<[keyof Nl2AgentRequirementsSummary, string]> = [
  ["goal", "goal"],
  ["audience_or_scenario", "audienceOrScenario"],
  ["primary_input", "primaryInput"],
  ["expected_output", "expectedOutput"],
  ["key_constraints", "keyConstraints"],
];

export const RequirementsSummaryCard: React.FC<
  RequirementsSummaryCardProps
> = ({ agentId, summary, workflowRevision }) => {
  const { t } = useTranslation();
  const workflow = useNl2AgentWorkflow();
  const lifecycle = useNl2AgentCardLifecycle(
    `requirements:${agentId}`,
    workflowRevision
  );
  const [confirmedLocally, setConfirmedLocally] = useState(false);
  const [confirmationError, setConfirmationError] = useState<string>();
  const summaryPayload = useMemo(
    () => toRequirementsSummaryRequest(summary),
    [summary]
  );
  const persistedStatus =
    workflow.sessionState?.resource_review.requirements_review.status;
  const confirmed = confirmedLocally || persistedStatus === "confirmed";

  const confirm = useCallback(async () => {
    if (!workflow.active || lifecycle.pending || confirmed) return;
    setConfirmationError(undefined);
    try {
      await lifecycle.execute(
        {
          action: "confirm_requirements",
          display_text: t(
            "nl2agent.action.confirmRequirements",
            "Requirements confirmed"
          ),
          payload: { summary: summaryPayload },
        },
        { onSuccess: () => setConfirmedLocally(true) }
      );
    } catch (error) {
      setConfirmationError(
        error instanceof Error
          ? error.message
          : t(
              "nl2agent.requirements.confirmationFailed",
              "Failed to confirm the requirements summary."
            )
      );
    }
  }, [confirmed, lifecycle, summaryPayload, t, workflow.active]);

  return (
    <ActionCard
      title={t("nl2agent.requirements.title", "Requirements Summary")}
    >
      <StaticFieldList
        fields={labels.map(([field, label]) => ({
          key: field,
          label: t(`nl2agent.requirements.${label}`),
          value: summary[field],
        }))}
      />
      {workflow.sessionStateLoading && !workflow.sessionState ? (
        <div className="mt-3 flex items-center gap-2 text-xs text-gray-500">
          <Spin size="small" />
          {t("nl2agent.requirements.loading", "Loading workflow state…")}
        </div>
      ) : confirmed ? (
        <Alert
          className="mt-3"
          type="success"
          showIcon
          title={t("nl2agent.requirements.confirmed", "Requirements confirmed")}
        />
      ) : (
        <div className="mt-3 space-y-2">
          <Alert
            type="info"
            title={t(
              "nl2agent.requirements.confirmInstruction",
              "Confirm this summary, or describe required changes in chat."
            )}
          />
          {confirmationError ? (
            <Alert
              type="error"
              title={t(
                "nl2agent.requirements.confirmationFailed",
                "Failed to confirm the requirements summary."
              )}
              description={confirmationError}
            />
          ) : null}
          <Button
            type="primary"
            loading={lifecycle.pending}
            disabled={!workflow.active || lifecycle.pending}
            icon={
              !lifecycle.pending ? (
                <CheckCircle2 className="h-3.5 w-3.5" />
              ) : undefined
            }
            onClick={() => void confirm()}
          >
            {lifecycle.pending
              ? t("nl2agent.requirements.confirming", "Confirming…")
              : t("nl2agent.requirements.confirm", "Confirm Requirements")}
          </Button>
        </div>
      )}
    </ActionCard>
  );
};

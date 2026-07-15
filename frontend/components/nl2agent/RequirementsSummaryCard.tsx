"use client";

import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Alert, Button, Spin } from "antd";
import { CheckCircle2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  confirmRequirementsSummary,
  registerRequirementsSummary,
  type Nl2AgentRequirementsSummary,
} from "@/services/nl2agentService";
import { useNl2AgentWorkflow } from "./Nl2AgentWorkflowContext";

export interface RequirementsSummaryCardProps {
  agentId: number;
  summary: Nl2AgentRequirementsSummary;
}

export interface RequirementsRegistrationState {
  status: "collecting" | "awaiting_confirmation" | "confirmed";
  fingerprint: string;
  isCurrent: boolean;
}

export const resolveRequirementsCardState = (
  loading: boolean,
  registrationError: string | undefined,
  registration: RequirementsRegistrationState | undefined
): "loading" | "error" | "superseded" | "confirmed" | "awaiting" | "idle" => {
  if (loading) return "loading";
  if (registrationError) return "error";
  if (registration && !registration.isCurrent) return "superseded";
  if (registration?.status === "confirmed") return "confirmed";
  if (registration?.status === "awaiting_confirmation") return "awaiting";
  return "idle";
};

const labels: Array<[keyof Nl2AgentRequirementsSummary, string]> = [
  ["goal", "goal"],
  ["audience_or_scenario", "audienceOrScenario"],
  ["primary_input", "primaryInput"],
  ["expected_output", "expectedOutput"],
  ["key_constraints", "keyConstraints"],
];

export const RequirementsSummaryCard: React.FC<
  RequirementsSummaryCardProps
> = ({ agentId, summary }) => {
  const { t } = useTranslation();
  const workflow = useNl2AgentWorkflow();
  const [loading, setLoading] = useState(true);
  const [confirming, setConfirming] = useState(false);
  const [registration, setRegistration] =
    useState<RequirementsRegistrationState>();
  const [registrationError, setRegistrationError] = useState<string>();
  const [confirmationError, setConfirmationError] = useState<string>();
  const serializedSummary = useMemo(() => JSON.stringify(summary), [summary]);
  const summaryPayload = useMemo(
    () => JSON.parse(serializedSummary) as Nl2AgentRequirementsSummary,
    [serializedSummary]
  );
  const blockerKey = `requirements-summary:${agentId}`;
  const {
    active,
    beginAction,
    endAction,
    notifyStateChanged,
    setInputBlocked,
    stateVersion,
  } = workflow;
  const lastStateVersionRef = useRef(stateVersion);

  const register = useCallback(
    async (notify = true) => {
      if (!active) {
        setLoading(false);
        return;
      }
      beginAction();
      setLoading(true);
      setRegistrationError(undefined);
      try {
        const result = await registerRequirementsSummary(
          agentId,
          summaryPayload
        );
        setRegistration({
          status: result.status,
          fingerprint: result.fingerprint,
          isCurrent: result.is_current,
        });
        setInputBlocked(blockerKey, false);
        if (notify) notifyStateChanged();
      } catch (registrationError) {
        setRegistration(undefined);
        setRegistrationError(
          registrationError instanceof Error
            ? registrationError.message
            : t(
                "nl2agent.requirements.registrationFailed",
                "Failed to register the requirements summary."
              )
        );
        setInputBlocked(blockerKey, true);
      } finally {
        setLoading(false);
        endAction();
      }
    },
    [
      active,
      agentId,
      beginAction,
      blockerKey,
      endAction,
      notifyStateChanged,
      setInputBlocked,
      summaryPayload,
      t,
    ]
  );

  const confirm = useCallback(async () => {
    if (
      !active ||
      !registration?.isCurrent ||
      registration.status !== "awaiting_confirmation" ||
      confirming
    ) {
      return;
    }
    beginAction();
    setConfirming(true);
    setConfirmationError(undefined);
    try {
      const result = await confirmRequirementsSummary(
        agentId,
        registration.fingerprint
      );
      setRegistration((current) =>
        current ? { ...current, status: "confirmed" } : current
      );
      notifyStateChanged();
      await workflow.continueWithText(result.chat_injection_text);
    } catch (confirmationFailure) {
      setConfirmationError(
        confirmationFailure instanceof Error
          ? confirmationFailure.message
          : t(
              "nl2agent.requirements.confirmationFailed",
              "Failed to confirm the requirements summary."
            )
      );
    } finally {
      setConfirming(false);
      endAction();
    }
  }, [
    active,
    agentId,
    beginAction,
    confirming,
    endAction,
    notifyStateChanged,
    registration,
    t,
    workflow,
  ]);

  useEffect(() => {
    void register(true);
    return () => setInputBlocked(blockerKey, false);
  }, [blockerKey, register, setInputBlocked]);

  useEffect(() => {
    if (stateVersion === lastStateVersionRef.current) return;
    lastStateVersionRef.current = stateVersion;
    void register(false);
  }, [register, stateVersion]);

  const cardState = resolveRequirementsCardState(
    loading,
    registrationError,
    registration
  );

  return (
    <div className="my-3 rounded-lg border border-gray-200 bg-white p-4">
      <div className="mb-3 text-sm font-medium">
        {t("nl2agent.requirements.title", "Requirements Summary")}
      </div>
      <dl className="space-y-3">
        {labels.map(([field, label]) => (
          <div key={field}>
            <dt className="text-xs font-medium text-gray-500">
              {t(`nl2agent.requirements.${label}`)}
            </dt>
            <dd className="mt-0.5 whitespace-pre-wrap text-sm text-gray-800">
              {summary[field]}
            </dd>
          </div>
        ))}
      </dl>
      {cardState === "loading" ? (
        <div className="mt-3 flex items-center gap-2 text-xs text-gray-500">
          <Spin size="small" />
          {t("nl2agent.requirements.registering", "Registering summary…")}
        </div>
      ) : cardState === "error" ? (
        <Alert
          className="mt-3"
          type="error"
          message={t(
            "nl2agent.requirements.notRegistered",
            "Requirements summary was not registered."
          )}
          description={registrationError}
          action={
            <Button onClick={() => void register(true)}>
              {t("nl2agent.requirements.retry", "Retry")}
            </Button>
          }
        />
      ) : cardState === "superseded" ? (
        <Alert
          className="mt-3"
          type="warning"
          message={t(
            "nl2agent.requirements.superseded",
            "This summary has been replaced by a newer version."
          )}
        />
      ) : cardState === "confirmed" ? (
        <Alert
          className="mt-3"
          type="success"
          showIcon
          message={t(
            "nl2agent.requirements.confirmed",
            "Requirements confirmed"
          )}
        />
      ) : cardState === "awaiting" ? (
        <div className="mt-3 space-y-2">
          <Alert
            type="info"
            message={t(
              "nl2agent.requirements.confirmInstruction",
              "Confirm this summary, or describe required changes in chat."
            )}
          />
          {confirmationError ? (
            <Alert
              type="error"
              message={t(
                "nl2agent.requirements.confirmationFailed",
                "Failed to confirm the requirements summary."
              )}
              description={confirmationError}
            />
          ) : null}
          <Button
            type="primary"
            loading={confirming}
            disabled={confirming}
            icon={
              !confirming ? <CheckCircle2 className="h-3.5 w-3.5" /> : undefined
            }
            onClick={() => void confirm()}
          >
            {confirming
              ? t("nl2agent.requirements.confirming", "Confirming…")
              : t("nl2agent.requirements.confirm", "Confirm Requirements")}
          </Button>
        </div>
      ) : null}
    </div>
  );
};

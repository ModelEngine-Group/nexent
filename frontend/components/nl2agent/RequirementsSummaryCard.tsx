"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Button, Spin } from "antd";

import {
  registerRequirementsSummary,
  type Nl2AgentRequirementsSummary,
} from "@/services/nl2agentService";
import { useNl2AgentWorkflow } from "./Nl2AgentWorkflowContext";

export interface RequirementsSummaryCardProps {
  agentId: number;
  summary: Nl2AgentRequirementsSummary;
}

const labels: Array<[keyof Nl2AgentRequirementsSummary, string]> = [
  ["goal", "Agent Goal"],
  ["audience_or_scenario", "Audience / Scenario"],
  ["primary_input", "Primary Input"],
  ["expected_output", "Expected Output"],
  ["key_constraints", "Key Constraints"],
];

export const RequirementsSummaryCard: React.FC<
  RequirementsSummaryCardProps
> = ({ agentId, summary }) => {
  const workflow = useNl2AgentWorkflow();
  const [loading, setLoading] = useState(true);
  const [registered, setRegistered] = useState(false);
  const [error, setError] = useState<string>();
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
  } = workflow;

  const register = useCallback(async () => {
    if (!active) {
      setLoading(false);
      return;
    }
    beginAction();
    setLoading(true);
    setError(undefined);
    try {
      await registerRequirementsSummary(agentId, summaryPayload);
      setRegistered(true);
      setInputBlocked(blockerKey, false);
      notifyStateChanged();
    } catch (registrationError) {
      setRegistered(false);
      setError(
        registrationError instanceof Error
          ? registrationError.message
          : "Failed to register the requirements summary."
      );
      setInputBlocked(blockerKey, true);
    } finally {
      setLoading(false);
      endAction();
    }
  }, [
    active,
    agentId,
    beginAction,
    blockerKey,
    endAction,
    notifyStateChanged,
    setInputBlocked,
    summaryPayload,
  ]);

  useEffect(() => {
    void register();
    return () => setInputBlocked(blockerKey, false);
  }, [blockerKey, register, setInputBlocked]);

  return (
    <div className="my-3 rounded-lg border border-gray-200 bg-white p-4">
      <div className="mb-3 text-sm font-medium">Requirements Summary</div>
      <dl className="space-y-3">
        {labels.map(([field, label]) => (
          <div key={field}>
            <dt className="text-xs font-medium text-gray-500">{label}</dt>
            <dd className="mt-0.5 whitespace-pre-wrap text-sm text-gray-800">
              {summary[field]}
            </dd>
          </div>
        ))}
      </dl>
      {loading ? (
        <div className="mt-3 flex items-center gap-2 text-xs text-gray-500">
          <Spin size="small" /> Registering summary…
        </div>
      ) : error ? (
        <Alert
          className="mt-3"
          type="error"
          message="Requirements summary was not registered."
          description={error}
          action={<Button onClick={() => void register()}>Retry</Button>}
        />
      ) : registered ? (
        <Alert
          className="mt-3"
          type="info"
          message="Reply in chat to confirm these requirements, or describe what should change."
        />
      ) : null}
    </div>
  );
};

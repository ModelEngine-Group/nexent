"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Alert, Button, Spin, message } from "antd";

import {
  completeOnlineResourceConfiguration,
  getNl2AgentSessionState,
  type Nl2AgentSessionState,
} from "@/services/nl2agentService";
import { useNl2AgentWorkflow } from "./Nl2AgentWorkflowContext";

export const getOnlineConfigurationBlockers = (
  review?: Nl2AgentSessionState["resource_review"]
) => {
  const batches = Object.values(review?.online_recommendation_batches ?? {});
  const mcpBatchCount = batches.filter(
    (batch) => batch.resource_type === "mcp"
  ).length;
  const skillBatchCount = batches.filter(
    (batch) => batch.resource_type === "skill"
  ).length;
  const missingCatalogs = [
    ...(mcpBatchCount === 0 ? ["MCP"] : []),
    ...(skillBatchCount === 0 ? ["Skill"] : []),
  ];
  const unresolvedMcpCount = Object.values(review?.mcp_workflows ?? {}).filter(
    (item) => item.status === "installing" || item.status === "connected"
  ).length;
  return {
    batches,
    mcpBatchCount,
    skillBatchCount,
    missingCatalogs,
    unresolvedMcpCount,
  };
};

export const OnlineConfigurationBar: React.FC<{
  agentId?: number | null;
}> = ({ agentId }) => {
  const workflow = useNl2AgentWorkflow();
  const [state, setState] = useState<Nl2AgentSessionState>();
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string>();

  const load = useCallback(async () => {
    if (!agentId) return;
    setLoading(true);
    setLoadError(undefined);
    try {
      setState(await getNl2AgentSessionState(agentId));
    } catch (error) {
      setLoadError(
        error instanceof Error
          ? error.message
          : "Failed to load online configuration."
      );
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    void load();
  }, [load, workflow.stateVersion]);

  if (!agentId || !workflow.active) return null;
  if (loading && !state)
    return <Spin size="small" className="mx-auto mb-2 block" />;
  if (loadError) {
    return (
      <Alert
        className="mx-auto mb-2 max-w-3xl"
        type="error"
        message="Unable to load online configuration state."
        description={loadError}
        action={<Button onClick={() => void load()}>Retry</Button>}
      />
    );
  }

  const review = state?.resource_review;
  const {
    batches,
    mcpBatchCount,
    skillBatchCount,
    missingCatalogs,
    unresolvedMcpCount,
  } = getOnlineConfigurationBlockers(review);
  if (batches.length === 0 || review?.online_configuration_confirmed)
    return null;

  const complete = async () => {
    if (!agentId) return;
    workflow.beginAction();
    try {
      const result = await completeOnlineResourceConfiguration(agentId);
      workflow.notifyStateChanged();
      message.success("Online resource configuration completed.");
      await workflow.continueWithText(result.chat_injection_text);
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : "Failed to complete online configuration."
      );
    } finally {
      workflow.endAction();
    }
  };

  return (
    <div className="mx-auto mb-2 flex max-w-3xl items-center justify-between gap-3 rounded-lg border border-sky-200 bg-sky-50 p-3">
      <div className="text-sm">
        <div className="font-medium">Online resource configuration</div>
        <div className="text-xs text-gray-500">
          {mcpBatchCount} MCP and {skillBatchCount} Skill recommendation
          batch(es) reviewed.
          {missingCatalogs.length > 0
            ? ` Waiting for the ${missingCatalogs.join(" and ")} search result card(s).`
            : unresolvedMcpCount > 0
              ? ` Resolve ${unresolvedMcpCount} connected MCP installation(s) first.`
              : " Finish when you no longer want to install more recommendations."}
        </div>
      </div>
      <Button
        type="primary"
        disabled={
          workflow.busy || missingCatalogs.length > 0 || unresolvedMcpCount > 0
        }
        onClick={() => void complete()}
      >
        Complete configuration
      </Button>
    </div>
  );
};

export const Nl2AgentContinuationError: React.FC = () => {
  const workflow = useNl2AgentWorkflow();
  if (!workflow.continuationError) return null;
  return (
    <Alert
      className="mx-auto mb-2 max-w-3xl"
      type="error"
      message="NL2AGENT could not continue automatically."
      description={workflow.continuationError}
      action={
        <Button
          disabled={workflow.busy}
          onClick={() => void workflow.retryContinuation()}
        >
          Retry continuation
        </Button>
      }
    />
  );
};

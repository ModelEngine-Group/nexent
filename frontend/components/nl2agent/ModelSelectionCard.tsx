"use client";

import React, { useEffect, useMemo, useState } from "react";
import { Alert, Button, Select, Spin, message } from "antd";
import { useTranslation } from "react-i18next";
import { getAvailablePlatformLlms } from "@/services/nl2agentService";
import { useNl2AgentWorkflow } from "./Nl2AgentWorkflowContext";
import { useNl2AgentCardLifecycle } from "./useNl2AgentCardLifecycle";

export const ModelSelectionCard: React.FC<{ agentId: number }> = ({
  agentId,
}) => {
  const { t } = useTranslation();
  const workflow = useNl2AgentWorkflow();
  const lifecycle = useNl2AgentCardLifecycle(`models:${agentId}`);
  const [models, setModels] = useState<
    Array<{ id: number; displayName: string }>
  >([]);
  const [primary, setPrimary] = useState<number>();
  const [fallbacks, setFallbacks] = useState<number[]>([]);
  const [saved, setSaved] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string>();
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const state = workflow.sessionState;
    if (
      state?.agent_id !== agentId ||
      !state.resource_review.model_selection_confirmed
    )
      return;
    setPrimary(state.business_logic_model_id ?? undefined);
    setFallbacks(
      state.models
        .filter((model) => model.role === "fallback")
        .map((model) => model.model_id)
    );
    setSaved(true);
  }, [agentId, workflow.sessionState]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setLoadError(undefined);
    getAvailablePlatformLlms()
      .then((items) => {
        if (!active) return;
        setModels(items);
      })
      .catch(() => {
        if (active) setLoadError("Failed to load available platform LLMs.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [reloadKey]);

  const options = useMemo(
    () =>
      models.map((model) => ({ value: model.id, label: model.displayName })),
    [models]
  );

  const save = async () => {
    if (!primary) return message.warning("Select a primary LLM.");
    const fallbackModelIds = fallbacks.filter((id) => id !== primary);
    const selectedNames = [primary, ...fallbackModelIds]
      .map((id) => models.find((model) => model.id === id)?.displayName)
      .filter((name): name is string => Boolean(name));
    try {
      await lifecycle.execute(
        {
          action: "save_model_selection",
          display_text: t("nl2agent.action.saveModelSelection", {
            defaultValue: "Models selected: {{models}}",
            models: selectedNames.join(", "),
          }),
          payload: {
            primary_model_id: primary,
            fallback_model_ids: fallbackModelIds,
          },
        },
        {
          onSuccess: () => {
            setSaved(true);
            message.success("LLM selection saved.");
          },
        }
      );
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : "Failed to save models."
      );
    }
  };

  return (
    <div className="my-2 rounded-lg border border-violet-200 bg-violet-50/40 p-3">
      <div className="mb-2 text-sm font-medium">Choose runtime LLMs</div>
      {loading && <Spin size="small" className="mb-2" />}
      {loadError && (
        <Alert
          className="mb-2"
          type="error"
          title={loadError}
          action={
            <Button size="small" onClick={() => setReloadKey((key) => key + 1)}>
              Retry
            </Button>
          }
        />
      )}
      {workflow.active && workflow.sessionStateError && (
        <Alert
          className="mb-2"
          type="error"
          title="Failed to restore saved model selection."
          action={
            <Button
              size="small"
              onClick={() => void workflow.refreshSessionState()}
            >
              Retry
            </Button>
          }
        />
      )}
      {!loading && !loadError && models.length === 0 && (
        <Alert
          className="mb-2"
          type="warning"
          title="No available LLMs are configured in the platform."
        />
      )}
      <Select
        className="mb-2 w-full"
        placeholder="Primary LLM"
        options={options}
        value={primary}
        onChange={setPrimary}
        disabled={
          saved ||
          loading ||
          workflow.sessionStateLoading ||
          Boolean(loadError) ||
          Boolean(workflow.sessionStateError) ||
          models.length === 0
        }
      />
      <Select
        mode="multiple"
        maxCount={4}
        className="mb-2 w-full"
        placeholder="Fallback LLMs in priority order"
        options={options.filter((option) => option.value !== primary)}
        value={fallbacks}
        onChange={setFallbacks}
        disabled={
          saved ||
          loading ||
          workflow.sessionStateLoading ||
          Boolean(loadError) ||
          Boolean(workflow.sessionStateError) ||
          models.length === 0
        }
      />
      <Button
        type="primary"
        loading={lifecycle.pending}
        disabled={
          saved ||
          loading ||
          workflow.sessionStateLoading ||
          Boolean(loadError) ||
          Boolean(workflow.sessionStateError) ||
          models.length === 0 ||
          !primary
        }
        onClick={save}
      >
        {saved ? "Models saved" : "Save model selection"}
      </Button>
    </div>
  );
};

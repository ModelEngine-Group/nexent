"use client";

import React, { useEffect, useMemo, useState } from "react";
import { Alert, Button, Select, Spin, message } from "antd";
import {
  getAvailablePlatformLlms,
  selectNl2AgentModels,
} from "@/services/nl2agentService";
import { useNl2AgentCardLifecycle } from "./useNl2AgentCardLifecycle";

export const ModelSelectionCard: React.FC<{ agentId: number }> = ({
  agentId,
}) => {
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
    try {
      await lifecycle.execute(
        () =>
          selectNl2AgentModels(
            agentId,
            primary,
            fallbacks.filter((id) => id !== primary)
          ),
        {
          onSuccess: () => {
            setSaved(true);
            message.success("LLM selection saved.");
          },
          continuationText: (result) => result.chat_injection_text,
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
          message={loadError}
          action={
            <Button size="small" onClick={() => setReloadKey((key) => key + 1)}>
              Retry
            </Button>
          }
        />
      )}
      {!loading && !loadError && models.length === 0 && (
        <Alert
          className="mb-2"
          type="warning"
          message="No available LLMs are configured in the platform."
        />
      )}
      <Select
        className="mb-2 w-full"
        placeholder="Primary LLM"
        options={options}
        value={primary}
        onChange={setPrimary}
        disabled={saved || loading || Boolean(loadError) || models.length === 0}
      />
      <Select
        mode="multiple"
        maxCount={4}
        className="mb-2 w-full"
        placeholder="Fallback LLMs in priority order"
        options={options.filter((option) => option.value !== primary)}
        value={fallbacks}
        onChange={setFallbacks}
        disabled={saved || loading || Boolean(loadError) || models.length === 0}
      />
      <Button
        type="primary"
        loading={lifecycle.pending}
        disabled={
          saved ||
          loading ||
          Boolean(loadError) ||
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

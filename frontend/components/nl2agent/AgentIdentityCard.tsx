"use client";

import React, { useEffect, useState } from "react";
import { Button, Input, message } from "antd";
import { CheckCircle2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getNl2AgentSessionState } from "@/services/nl2agentService";
import { useNl2AgentCardLifecycle } from "./useNl2AgentCardLifecycle";
import { ActionCard } from "./ActionCard";

export interface AgentIdentityCardProps {
  agentId: number;
  suggestedDisplayName?: string;
  workflowRevision?: number;
}

export const AgentIdentityCard: React.FC<AgentIdentityCardProps> = ({
  agentId,
  suggestedDisplayName,
  workflowRevision,
}) => {
  const { t } = useTranslation();
  const lifecycle = useNl2AgentCardLifecycle(
    `identity:${agentId}`,
    workflowRevision
  );
  const normalizedSuggestion = (suggestedDisplayName || "").trim().slice(0, 50);
  const [displayName, setDisplayName] = useState(normalizedSuggestion);
  const [internalName, setInternalName] = useState("");
  const [loading, setLoading] = useState(true);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    void getNl2AgentSessionState(agentId)
      .then((state) => {
        setDisplayName(
          state.identity_confirmed
            ? state.display_name || ""
            : normalizedSuggestion
        );
        setInternalName(state.identity_confirmed ? state.internal_name : "");
        setSaved(state.identity_confirmed);
      })
      .catch((error) =>
        message.error(error?.message || "Failed to load agent identity.")
      )
      .finally(() => setLoading(false));
  }, [agentId, normalizedSuggestion]);

  const save = async () => {
    const value = displayName.trim();
    if (!value) {
      message.warning("Enter an agent display name.");
      return;
    }
    try {
      await lifecycle.execute(
        {
          action: "save_identity",
          display_text: t("nl2agent.action.saveIdentity", {
            defaultValue: "Agent name saved: {{name}}",
            name: value,
          }),
          payload: { display_name: value },
        },
        {
          onSuccess: (response) => {
            const result = response.result as {
              display_name?: string;
              internal_name?: string;
            };
            setDisplayName(result.display_name || value);
            setInternalName(result.internal_name || "");
            setSaved(true);
            message.success("Agent identity saved.");
          },
        }
      );
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : "Failed to save agent identity."
      );
    }
  };

  return (
    <ActionCard title="Agent Identity">
      <label className="mb-1 block text-xs text-gray-500">
        Agent Display Name
      </label>
      <Input
        value={displayName}
        maxLength={50}
        disabled={saved}
        onChange={(event) => setDisplayName(event.target.value)}
        placeholder="Enter the user-facing agent title"
      />
      {internalName ? (
        <div className="mt-2 text-xs text-gray-500">
          Internal Variable Name:{" "}
          <span className="font-mono">{internalName}</span>
        </div>
      ) : null}
      <Button
        className="mt-3"
        type="primary"
        size="small"
        loading={loading || lifecycle.pending}
        disabled={saved || !displayName.trim()}
        onClick={save}
        icon={saved ? <CheckCircle2 className="h-3.5 w-3.5" /> : undefined}
      >
        {saved ? "Identity Saved" : "Save Identity"}
      </Button>
    </ActionCard>
  );
};

"use client";

import React, { useEffect, useState } from "react";
import { Button, Input, message } from "antd";
import { CheckCircle2 } from "lucide-react";

import {
  getNl2AgentSessionState,
  saveNl2AgentIdentity,
} from "@/services/nl2agentService";

export interface AgentIdentityCardProps {
  agentId: number;
  suggestedDisplayName?: string;
}

export const AgentIdentityCard: React.FC<AgentIdentityCardProps> = ({
  agentId,
  suggestedDisplayName,
}) => {
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
    setLoading(true);
    try {
      const result = await saveNl2AgentIdentity(agentId, value);
      setDisplayName(result.display_name);
      setInternalName(result.internal_name);
      setSaved(true);
      message.success("Agent identity saved.");
    } catch (error: any) {
      message.error(error?.message || "Failed to save agent identity.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="my-3 rounded-lg border border-gray-200 bg-white p-4">
      <div className="mb-3 text-sm font-medium">Agent Identity</div>
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
        loading={loading}
        disabled={saved || !displayName.trim()}
        onClick={save}
        icon={saved ? <CheckCircle2 className="h-3.5 w-3.5" /> : undefined}
      >
        {saved ? "Identity Saved" : "Save Identity"}
      </Button>
    </div>
  );
};

"use client";

import { Alert, Select, Switch } from "antd";
import { useTranslation } from "react-i18next";
import { useAgentReadOnly } from "@/hooks/agent/useAgentReadOnly";
import { useAgentStore } from "@/stores/agentStore";
import type { AgentCore } from "@/types/agentConfig";

export default function AgentCoreSelector() {
  const { t } = useTranslation("common");
  const agent = useAgentStore((state) => state.editedAgent);
  const update = useAgentStore((state) => state.updateAgentConfig);
  const readOnly = useAgentReadOnly();
  if (!agent) return null;
  const core = agent.agent_core ?? "smolagents";
  return (
    <div className="flex flex-col gap-3">
      <label htmlFor="agent-core">{t("agent.core.label")}</label>
      <Select<AgentCore>
        id="agent-core"
        aria-label={t("agent.core.label")}
        value={core}
        disabled={readOnly}
        options={[
          { value: "smolagents", label: "smolagents" },
          { value: "jiuwen", label: "Jiuwen" },
        ]}
        onChange={(agent_core) => update({ agent_core })}
      />
      {core === "jiuwen" && (
        <Alert type="info" showIcon title={t("agent.core.jiuwenHint")} />
      )}
      <div className="flex items-center justify-between gap-3">
        <label htmlFor="agent-context-manager">
          {t("agent.core.contextManager")}
        </label>
        <Switch
          id="agent-context-manager"
          aria-label={t("agent.core.contextManager")}
          checked={agent.enable_context_manager ?? true}
          disabled={readOnly}
          onChange={(enable_context_manager) =>
            update({ enable_context_manager })
          }
        />
      </div>
    </div>
  );
}

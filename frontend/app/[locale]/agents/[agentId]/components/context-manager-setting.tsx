// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";

import { Switch } from "antd";
import { useTranslation } from "react-i18next";
import { useAgentReadOnly } from "@/hooks/agent/useAgentReadOnly";
import { useAgentStore } from "@/stores/agentStore";

export default function ContextManagerSetting() {
  const { t } = useTranslation("common");
  const agent = useAgentStore((state) => state.editedAgent);
  const update = useAgentStore((state) => state.updateAgentConfig);
  const readOnly = useAgentReadOnly();
  if (!agent) return null;
  return (
    <div className="flex flex-col gap-3">
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

"use client";

import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, message as AntMessage } from "antd";
import { Download, CheckCircle2, Loader2 } from "lucide-react";
import {
  installWebSkill,
  type Nl2AgentInstallWebSkillPayload,
} from "@/services/nl2agentService";
import { useNl2AgentCardLifecycle } from "./useNl2AgentCardLifecycle";
import { useNl2AgentWorkflow } from "./Nl2AgentWorkflowContext";
import type { WebSkillCardItem } from "./cardPayloadTypes";

export type { WebSkillCardItem } from "./cardPayloadTypes";

export interface WebSkillCardProps {
  agentId: number;
  item: WebSkillCardItem;
}

/**
 * Renders a single official/web skill recommendation with an "Install" button.
 * Clicking Install calls POST /nl2agent/session/{agentId}/install-web-skill
 * which installs the tenant Skill and binds it to the draft agent. Each web
 * skill installs individually — no batch.
 *
 * Rendered from a ```nl2agent-web-skill fenced JSON block.
 */
export const WebSkillCard: React.FC<WebSkillCardProps> = ({
  agentId,
  item,
}) => {
  const workflow = useNl2AgentWorkflow();
  const lifecycle = useNl2AgentCardLifecycle(
    `web-skill:${agentId}:${item.skill_id ?? item.skill_name ?? item.name}`
  );
  const { t } = useTranslation("common");
  const [installed, setInstalled] = useState(item.status === "installed");

  React.useEffect(() => {
    const normalizedName = (item.skill_name || item.name).trim().toLowerCase();
    const restored = workflow.sessionState?.skills.some(
      (skill) =>
        skill.origin === "online" &&
        (skill.skill_id === item.skill_id ||
          skill.name.trim().toLowerCase() === normalizedName)
    );
    if (restored) setInstalled(true);
  }, [item.name, item.skill_id, item.skill_name, workflow.sessionState]);

  const handleInstall = async () => {
    try {
      const payload: Nl2AgentInstallWebSkillPayload = {
        skill_name: item.skill_name || item.name,
      };
      if (typeof item.skill_id === "number" && item.skill_id > 0) {
        payload.skill_id = item.skill_id;
      }
      await lifecycle.execute(() => installWebSkill(agentId, payload), {
        onSuccess: () => {
          AntMessage.success(
            t("nl2agent.webSkill.installed", {
              defaultValue: 'Skill "{{name}}" installed.',
              name: item.name,
            })
          );
          setInstalled(true);
        },
        notifyStateChanged: true,
      });
    } catch (error) {
      AntMessage.error(
        error instanceof Error ? error.message : "Failed to install skill."
      );
    }
  };

  return (
    <div className="my-2 border border-violet-200 rounded-lg p-3 bg-violet-50/40">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-sm">{item.name}</span>
            {typeof item.score === "number" && (
              <span className="text-[10px] text-gray-500">
                score: {item.score}
              </span>
            )}
            {item.tags && item.tags.length > 0 && (
              <div className="flex gap-1 flex-wrap">
                {item.tags.slice(0, 4).map((tag) => (
                  <span
                    key={tag}
                    className="text-[10px] px-1.5 py-0.5 rounded bg-violet-50 text-violet-700 border border-violet-200"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            )}
          </div>
          {item.description && (
            <div className="text-xs text-gray-600 mt-1">{item.description}</div>
          )}
          {item.reason && (
            <div className="text-xs text-gray-400 mt-1 italic">
              {item.reason}
            </div>
          )}
        </div>
        <Button
          size="small"
          disabled={installed || lifecycle.pending}
          loading={lifecycle.pending}
          icon={
            installed ? (
              <CheckCircle2 className="h-3.5 w-3.5" />
            ) : lifecycle.pending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Download className="h-3.5 w-3.5" />
            )
          }
          onClick={handleInstall}
        >
          {installed
            ? t("nl2agent.webSkill.installedShort", "Installed")
            : t("nl2agent.webSkill.install", "Install")}
        </Button>
      </div>
    </div>
  );
};

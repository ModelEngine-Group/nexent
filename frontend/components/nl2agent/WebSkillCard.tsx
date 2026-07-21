"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Button, message as AntMessage } from "antd";
import { Download, CheckCircle2, Loader2 } from "lucide-react";
import {
  installWebSkill,
  getWebSkillConfiguration,
  type Nl2AgentInstallWebSkillPayload,
  type Nl2AgentWebSkillConfiguration,
} from "@/services/nl2agentService";
import { useNl2AgentCardLifecycle } from "./useNl2AgentCardLifecycle";
import { useNl2AgentWorkflow } from "./Nl2AgentWorkflowContext";
import { WebSkillConfigurationModal } from "./WebSkillConfigurationModal";
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
  const [configuration, setConfiguration] =
    useState<Nl2AgentWebSkillConfiguration>();
  const [configurationLoading, setConfigurationLoading] = useState(false);
  const [configurationError, setConfigurationError] = useState<string>();
  const [configurationOpen, setConfigurationOpen] = useState(false);

  const loadConfiguration = useCallback(async () => {
    setConfigurationLoading(true);
    setConfigurationError(undefined);
    try {
      setConfiguration(
        await getWebSkillConfiguration(agentId, {
          skill_id: item.skill_id,
          skill_name: item.skill_name || item.name,
        })
      );
    } catch (error) {
      setConfigurationError(
        error instanceof Error
          ? error.message
          : "Failed to load Skill configuration."
      );
    } finally {
      setConfigurationLoading(false);
    }
  }, [agentId, item.name, item.skill_id, item.skill_name]);

  useEffect(() => {
    if (workflow.active && !installed) void loadConfiguration();
  }, [installed, loadConfiguration, workflow.active]);

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

  const performInstall = async (configValues: Record<string, unknown>) => {
    try {
      const payload: Nl2AgentInstallWebSkillPayload = {
        skill_name: item.skill_name || item.name,
        config_values: configValues,
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
      return true;
    } catch (error) {
      AntMessage.error(
        error instanceof Error ? error.message : "Failed to install skill."
      );
      return false;
    }
  };

  const configSchemas = configuration?.config_schemas ?? [];

  const handleInstall = () => {
    if (configSchemas.length > 0) {
      setConfigurationOpen(true);
      return;
    }
    void performInstall({});
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
          disabled={
            installed ||
            lifecycle.pending ||
            configurationLoading ||
            Boolean(configurationError) ||
            !configuration
          }
          loading={lifecycle.pending || configurationLoading}
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
            : configSchemas.length > 0
              ? t("nl2agent.webSkill.configureInstall", "Configure & Install")
              : t("nl2agent.webSkill.install", "Install")}
        </Button>
      </div>
      {configurationError ? (
        <Alert
          className="mt-2"
          type="error"
          showIcon
          message={configurationError}
          action={
            <Button size="small" onClick={() => void loadConfiguration()}>
              Retry
            </Button>
          }
        />
      ) : null}
      {configuration && configSchemas.length > 0 ? (
        <WebSkillConfigurationModal
          open={configurationOpen}
          onCancel={() => setConfigurationOpen(false)}
          onSubmit={performInstall}
          skillName={configuration.skill_name}
          schemas={configSchemas}
          defaults={configuration.config_values ?? {}}
        />
      ) : null}
    </div>
  );
};

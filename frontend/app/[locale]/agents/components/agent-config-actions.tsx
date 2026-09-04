"use client";

import { useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import { App, Button, Modal, Tooltip } from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, FileOutput, Globe, Network, Trash2 } from "lucide-react";

import A2AServerSettingsPanel from "./a2a/A2AServerSettingsPanel";
import AgentCallRelationshipModal from "@/components/agent/AgentCallRelationshipModal";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import { useAgentInfo } from "@/hooks/agent/useAgentInfo";
import log from "@/lib/logger";
import { a2aClientService } from "@/services/a2aService";
import {
  deleteAgent,
  exportAgent,
  searchAgentInfo,
  updateAgentInfo,
  updateToolConfig,
} from "@/services/agentConfigService";
import { useAgentStore } from "@/stores/agentStore";

export default function AgentConfigActions() {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const confirm = useConfirmModal();
  const queryClient = useQueryClient();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const agentId = useAgentStore((state) => state.agentId);
  const editedAgent = useAgentStore((state) => state.editedAgent);
  const isReadOnly = useAgentStore((state) => state.isReadOnly);
  const reset = useAgentStore((state) => state.reset);
  const agentName = editedAgent?.display_name || editedAgent?.name || "agent";
  const { agentInfo } = useAgentInfo(agentId);
  const [isRelationshipVisible, setIsRelationshipVisible] = useState(false);
  const [isA2ASettingsVisible, setIsA2ASettingsVisible] = useState(false);
  const { data: a2aSettingsData, isLoading: isLoadingA2ASettings } = useQuery({
    queryKey: ["a2aServerSettings", agentId],
    queryFn: () => a2aClientService.getServerSettings(agentId!),
    enabled: isA2ASettingsVisible && agentId !== null,
  });

  const updateAgentMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) => updateAgentInfo(payload),
  });
  const deleteAgentMutation = useMutation({
    mutationFn: (id: number) => deleteAgent(id),
  });

  const handleExport = async () => {
    if (agentId === null) return;

    try {
      const result = await exportAgent(agentId);
      if (!result.success) {
        message.error(
          result.message || t("businessLogic.config.error.agentExportFailed")
        );
        return;
      }

      if (result.data) {
        const blob = new Blob([JSON.stringify(result.data, null, 2)], {
          type: "application/json",
        });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `${agentName || "agent"}.json`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
      }

      message.success(t("businessLogic.config.message.agentExportSuccess"));
    } catch (error) {
      log.error("Failed to export agent:", error);
      message.error(t("businessLogic.config.error.agentExportFailed"));
    }
  };

  const handleCopy = async () => {
    if (agentId === null) return;

    try {
      const detailResult = await searchAgentInfo(agentId);
      if (!detailResult.success || !detailResult.data) {
        message.error(detailResult.message);
        return;
      }
      const detail = detailResult.data;
      const tools = Array.isArray(detail.tools) ? detail.tools : [];
      const unavailableTools = tools.filter(
        (tool: any) => tool && tool.is_available === false
      );
      const unavailableToolNames = unavailableTools
        .map(
          (tool: any) =>
            tool?.display_name || tool?.name || tool?.tool_name || ""
        )
        .filter((name: string) => Boolean(name));
      const enabledToolIds = tools
        .filter((tool: any) => tool && tool.is_available !== false)
        .map((tool: any) => Number(tool.id))
        .filter((id: number) => Number.isFinite(id));
      const subAgentIds = (
        Array.isArray(detail.sub_agent_id_list) ? detail.sub_agent_id_list : []
      )
        .map((id: any) => Number(id))
        .filter((id: number) => Number.isFinite(id));
      const modelIdsForCopy = (() => {
        if (detail.model_ids && detail.model_ids.length > 0) {
          return detail.model_ids;
        }
        const legacySingleId = (detail as { model_id?: number }).model_id;
        return legacySingleId ? [legacySingleId] : undefined;
      })();

      const createResult = await updateAgentMutation.mutateAsync({
        agent_id: undefined,
        name: `${detail.name || "agent"}_copy`,
        display_name: `${
          detail.display_name || t("agentConfig.agents.defaultDisplayName")
        }${t("agent.copySuffix")}`,
        description: detail.description,
        author: detail.author,
        model_ids: modelIdsForCopy,
        max_steps: detail.max_step,
        is_main_agent: detail.is_main_agent ?? true,
        provide_run_summary: detail.provide_run_summary,
        enabled: detail.enabled,
        business_description: detail.business_description,
        duty_prompt: detail.duty_prompt,
        constraint_prompt: detail.constraint_prompt,
        few_shots_prompt: detail.few_shots_prompt,
        business_logic_model_name: detail.business_logic_model_name ?? undefined,
        business_logic_model_id: detail.business_logic_model_id ?? undefined,
        enabled_tool_ids: enabledToolIds,
        related_agent_ids: subAgentIds,
      });

      if (!createResult.success || !createResult.data?.agent_id) {
        message.error(createResult.message || t("agentConfig.agents.copyFailed"));
        return;
      }
      const newAgentId = Number(createResult.data.agent_id);

      for (const tool of tools) {
        if (!tool || tool.is_available === false) continue;
        const params =
          tool.initParams?.reduce((acc: Record<string, any>, param: any) => {
            acc[param.name] = param.value;
            return acc;
          }, {}) || {};
        try {
          await updateToolConfig(Number(tool.id), newAgentId, params, true);
        } catch (error) {
          log.error("Failed to copy tool configuration:", error);
          message.error(t("agentConfig.agents.copyFailed"));
          return;
        }
      }

      queryClient.invalidateQueries({ queryKey: ["agents"] });
      message.success(t("agentConfig.agents.copySuccess"));

      if (unavailableTools.length > 0) {
        const names =
          unavailableToolNames.join(", ") ||
          unavailableTools
            .map((tool: any) => Number(tool?.id))
            .filter((id: number) => !Number.isNaN(id))
            .join(", ");
        message.warning(
          t("agentConfig.agents.copyUnavailableTools", {
            count: unavailableTools.length,
            names,
          })
        );
      }
    } catch (error) {
      log.error("Failed to copy agent:", error);
      message.error(t("agentConfig.agents.copyFailed"));
    }
  };

  const handleDelete = () => {
    if (agentId === null) return;

    deleteAgentMutation.mutate(agentId, {
      onSuccess: () => {
        message.success(
          t("businessLogic.config.error.agentDeleteSuccess", { name: agentName })
        );
        const nextSearchParams = new URLSearchParams(searchParams.toString());
        nextSearchParams.delete("agent_id");
        const query = nextSearchParams.toString();
        router.replace(query ? `${pathname}?${query}` : pathname);
        reset();
        queryClient.invalidateQueries({ queryKey: ["agents"] });
        queryClient.invalidateQueries({ queryKey: ["publishedAgentsList"] });
      },
      onError: () => {
        message.error(t("businessLogic.config.error.agentDeleteFailed"));
      },
    });
  };

  const disabled = agentId === null;

  return (
    <>
      <div className="flex items-center gap-1">
        {(agentInfo as { is_a2a?: boolean } | null)?.is_a2a && (
          <Tooltip title={t("a2a.agent.viewA2ASettings")}>
            <Button
              type="text"
              size="small"
              icon={<Globe className="h-4 w-4" />}
              disabled={disabled}
              className="flex h-8 w-8 items-center justify-center rounded-md !text-muted-foreground hover:!bg-muted hover:!text-foreground disabled:!opacity-30"
              onClick={() => setIsA2ASettingsVisible(true)}
            />
          </Tooltip>
        )}
        <Tooltip title={t("agent.contextMenu.copy")}>
          <Button
            type="text"
            size="small"
            icon={<Copy className="h-4 w-4" />}
            disabled={disabled}
            className="flex h-8 w-8 items-center justify-center rounded-md !text-muted-foreground hover:!bg-muted hover:!text-foreground disabled:!opacity-30"
            onClick={() =>
              confirm.confirm({
                title: t("agentConfig.agents.copyConfirmTitle"),
                content: t("agentConfig.agents.copyConfirmContent", {
                  name: agentName,
                }),
                onOk: handleCopy,
              })
            }
          />
        </Tooltip>
        <Tooltip title={t("agent.action.viewCallRelationship")}>
          <Button
            type="text"
            size="small"
            icon={<Network className="h-4 w-4" />}
            disabled={disabled}
            className="flex h-8 w-8 items-center justify-center rounded-md !text-muted-foreground hover:!bg-muted hover:!text-foreground disabled:!opacity-30"
            onClick={() => setIsRelationshipVisible(true)}
          />
        </Tooltip>
        <Tooltip title={t("agent.contextMenu.export")}>
          <Button
            type="text"
            size="small"
            icon={<FileOutput className="h-4 w-4" />}
            disabled={disabled}
            className="flex h-8 w-8 items-center justify-center rounded-md !text-muted-foreground hover:!bg-muted hover:!text-foreground disabled:!opacity-30"
            onClick={handleExport}
          />
        </Tooltip>
        <Tooltip
          title={
            isReadOnly
              ? t("agent.noEditPermission")
              : t("agent.contextMenu.delete")
          }
        >
          <Button
            type="text"
            size="small"
            icon={<Trash2 className="h-4 w-4" />}
            disabled={disabled || isReadOnly}
            className="flex h-8 w-8 items-center justify-center rounded-md !text-muted-foreground hover:!bg-muted hover:!text-foreground disabled:!opacity-30"
            onClick={() =>
              confirm.confirm({
                title: t("businessLogic.config.modal.deleteTitle"),
                content: t("businessLogic.config.modal.deleteContent", {
                  name: agentName,
                }),
                onOk: handleDelete,
              })
            }
          />
        </Tooltip>
      </div>
      {agentId !== null && (
        <AgentCallRelationshipModal
          visible={isRelationshipVisible}
          onClose={() => setIsRelationshipVisible(false)}
          agentId={agentId}
          agentName={agentName}
        />
      )}
      <Modal
        centered
        width={640}
        title={t("a2a.server.previewTitle")}
        open={isA2ASettingsVisible}
        onCancel={() => setIsA2ASettingsVisible(false)}
        loading={isLoadingA2ASettings}
        footer={null}
        zIndex={1050}
      >
        {a2aSettingsData?.data ? (
          <A2AServerSettingsPanel
            endpointId={a2aSettingsData.data.endpoint_id}
            supportedInterfaces={a2aSettingsData.data.supported_interfaces}
          />
        ) : (
          <div style={{ textAlign: "center", padding: "40px 0", color: "#999" }}>
            {t(
              "a2a.service.getServerSettingsFailed",
              "Failed to load A2A settings"
            )}
          </div>
        )}
      </Modal>
    </>
  );
}

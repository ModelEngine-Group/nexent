"use client";

import { Button, Input, Modal, Tag } from "antd";
import { useTranslation } from "react-i18next";
import {
  MCP_TOOLS_MODAL_WRAP_CLASS,
  McpTransportType,
  mcpToolsModalChromeStyles,
} from "@/const/mcpTools";
import {
  getDeploymentTypeLabelKey,
  resolveDeploymentType,
} from "@/lib/mcpTools";
import TransportIcon from "../../shared/TransportIcon";
import type { useMcpCommunityQuickAdd } from "@/hooks/mcpTools/useMcpCommunityQuickAdd";

interface CommunityQuickAddModalProps {
  controller: ReturnType<typeof useMcpCommunityQuickAdd>;
}

export default function CommunityQuickAddModal({
  controller,
}: CommunityQuickAddModalProps) {
  const { t } = useTranslation("common");
  const { source, draft, submitting, updateDraft, close, confirm } = controller;

  if (!source || !draft) return null;

  const deploymentType = resolveDeploymentType(source);
  const deploymentLabel = t(getDeploymentTypeLabelKey(deploymentType));
  const isContainer = draft.transportType === McpTransportType.CONTAINER;

  return (
    <Modal
      open
      closable
      centered
      width={540}
      style={{ top: 20 }}
      onCancel={close}
      wrapClassName={`${MCP_TOOLS_MODAL_WRAP_CLASS}`}
      styles={mcpToolsModalChromeStyles()}
      footer={
        <div className="flex items-center justify-end gap-3">
          <Button onClick={close}>{t("common.cancel")}</Button>
          <Button
            type="primary"
            loading={submitting}
            onClick={confirm}
          >
            {t("mcpTools.community.quickAddConfirm")}
          </Button>
        </div>
      }
    >
      <div className="bg-white">
        {/* Header */}
        <div className="border-b border-slate-100 px-6 pt-6 pb-4">
          <div className="flex items-start gap-3">
            <TransportIcon
              transportType={source.transportType}
              deploymentType={deploymentType}
              label={deploymentLabel}
              className="!h-10 !w-10 rounded-xl"
            />
            <div className="min-w-0 flex-1">
              <h2 className="text-xl font-bold text-slate-900">
                {t("mcpTools.community.quickAddConfirmTitle", {
                  name: source.name,
                })}
              </h2>
            </div>
          </div>
        </div>

        {/* Content */}
        <div className="px-6 py-5 space-y-5">
          {/* Editable Name */}
          <div>
            <label className="mb-1.5 block text-sm font-medium text-slate-700">
              {t("mcpConfig.editServer.serviceName")}
            </label>
            <Input
              value={draft.name}
              onChange={(e) => updateDraft({ name: e.target.value })}
              autoComplete="off"
            />
          </div>

          {/* Description */}
          {draft.description && (
            <div>
              <label className="mb-1.5 block text-sm font-medium text-slate-700">
                {t("mcpTools.detail.description")}
              </label>
              <p className="text-sm leading-6 text-slate-600">
                {draft.description}
              </p>
            </div>
          )}

          {/* Server URL or Container Port */}
          {isContainer ? (
            <div>
              <label className="mb-1.5 block text-sm font-medium text-slate-700">
                {t("mcpTools.addModal.containerPort")}
              </label>
              <p className="text-sm font-medium text-slate-800">
                {draft.containerPort ?? "-"}
              </p>
            </div>
          ) : (
            <div>
              <label className="mb-1.5 block text-sm font-medium text-slate-700">
                {t("mcpConfig.editServer.mcpUrl")}
              </label>
              <p className="text-sm break-all text-slate-700 bg-slate-50 rounded-lg px-3 py-2">
                {draft.serverUrl || "-"}
              </p>
            </div>
          )}

          {/* Authorization Token */}
          {!isContainer && (
            <div>
              <label className="mb-1.5 block text-sm font-medium text-slate-700">
                {t("mcpConfig.editServer.authorizationToken")}
              </label>
              <Input.Password
                value={draft.authorizationToken}
                onChange={(e) => updateDraft({ authorizationToken: e.target.value })}
                placeholder={t("mcpConfig.editServer.authorizationTokenPlaceholder")}
                autoComplete="new-password"
              />
            </div>
          )}

          {/* Tags */}
          {draft.tags && draft.tags.length > 0 && (
            <div>
              <label className="mb-1.5 block text-sm font-medium text-slate-700">
                {t("mcpTools.detail.tags")}
              </label>
              <div className="flex flex-wrap gap-1.5">
                <Tag color="blue" className="m-0 rounded-full">
                  {deploymentLabel}
                </Tag>
                {draft.tags.map((tag) => (
                  <Tag
                    key={tag}
                    className="m-0 rounded-full bg-slate-100"
                  >
                    {tag}
                  </Tag>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}

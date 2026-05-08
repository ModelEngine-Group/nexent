import { useState } from "react";
import { Button, Modal, Tag } from "antd";
import { useTranslation } from "react-i18next";
import {
  MCP_TOOLS_MODAL_WRAP_CLASS,
  mcpToolsModalChromeStyles,
} from "@/const/mcpTools";
import {
  extractRegistryLinks,
  formatRegistryDate,
  formatRegistryVersion,
  getTransportLabelKey,
  toPrettyRegistryJson,
} from "@/lib/mcpTools";
import type { CommunityMcpCard } from "@/types/mcpTools";
import RegistryStatusBadge from "../../shared/StatusBadge";
import JsonPreviewModal from "../../shared/JsonPreviewModal";

const sectionCard =
  "rounded-xl border border-slate-200/90 bg-white p-4 shadow-sm";

interface McpCommunityDetailModalProps {
  service: CommunityMcpCard;
  onClose: () => void;
  onQuickAdd: (service: CommunityMcpCard) => void;
}

export default function McpCommunityDetailModal({
  service,
  onClose,
  onQuickAdd,
}: McpCommunityDetailModalProps) {
  const { t } = useTranslation("common");
  const [showServerJsonModal, setShowServerJsonModal] = useState(false);
  const [showConfigJsonModal, setShowConfigJsonModal] = useState(false);
  const { websiteUrl, repositoryUrl } = extractRegistryLinks(
    service.registryJson as Record<string, unknown>
  );
  const serverJsonPretty = toPrettyRegistryJson(
    service.registryJson as Record<string, unknown>
  );
  const configJsonPretty = toPrettyRegistryJson(
    (service.configJson || undefined) as Record<string, unknown> | undefined
  );
  const hasServerJson = Boolean(
    service.registryJson && Object.keys(service.registryJson).length > 0
  );
  const hasConfigJson = Boolean(
    service.configJson && Object.keys(service.configJson).length > 0
  );
  const serverTypeText = t(getTransportLabelKey(service.transportType));
  const sourceText = t("mcpTools.source.community");

  return (
    <>
      <Modal
        open
        footer={null}
        closable
        centered
        width={560}
        onCancel={onClose}
        wrapClassName={MCP_TOOLS_MODAL_WRAP_CLASS}
        styles={mcpToolsModalChromeStyles()}
      >
        <div>
          <div className="border-b border-slate-100 bg-white px-5 py-4">
            <h2 className="text-lg font-semibold tracking-tight text-slate-900">
              {t("mcpTools.detail.title")}
            </h2>
          </div>

          <div className="space-y-4 px-5 py-5">
            <div className={sectionCard}>
              <div className="grid gap-4">
                <div>
                  <p className="text-sm text-slate-500">
                    {t("mcpTools.detail.name")}
                  </p>
                  <p className="mt-1 break-all rounded-md border border-slate-200 bg-slate-50 px-4 py-2 text-sm font-medium text-slate-800">
                    {service.name || "-"}
                  </p>
                </div>
                <div>
                  <p className="text-sm text-slate-500">
                    {t("mcpTools.detail.description")}
                  </p>
                  <p className="mt-1 whitespace-pre-wrap break-words rounded-md border border-slate-200 bg-slate-50 px-4 py-2 text-sm font-medium text-slate-800">
                    {service.description || "-"}
                  </p>
                </div>
                <div>
                  <p className="text-sm text-slate-500">
                    {t("mcpTools.detail.serverUrl")}
                  </p>
                  <p className="mt-1 break-all rounded-md border border-slate-200 bg-slate-50 px-4 py-2 text-sm font-medium text-slate-800">
                    {service.serverUrl || "-"}
                  </p>
                </div>
              </div>
            </div>

            <div className={sectionCard}>
              <div className="grid gap-3 text-sm text-slate-700">
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">
                    {t("mcpTools.detail.source")}
                  </span>
                  <span className="font-medium text-slate-800">{sourceText}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">
                    {t("mcpTools.detail.serverType")}
                  </span>
                  <span className="font-medium text-slate-800">
                    {serverTypeText}
                  </span>
                </div>
                {service.version ? (
                  <div className="flex items-center justify-between">
                    <span className="text-slate-500">
                      {t("mcpTools.detail.version")}
                    </span>
                    <span className="font-medium text-slate-800">
                      {formatRegistryVersion(service.version)}
                    </span>
                  </div>
                ) : null}
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">
                    {t("mcpTools.detail.status")}
                  </span>
                  <RegistryStatusBadge status={service.status} />
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">
                    {t("mcpTools.community.publishedAt")}
                  </span>
                  <span className="font-medium text-slate-800">
                    {formatRegistryDate(service.createdAt)}
                  </span>
                </div>
                {service.updatedAt ? (
                  <div className="flex items-center justify-between">
                    <span className="text-slate-500">
                      {t("mcpTools.detail.updatedAt")}
                    </span>
                    <span className="font-medium text-slate-800">
                      {formatRegistryDate(service.updatedAt)}
                    </span>
                  </div>
                ) : null}
                {websiteUrl ? (
                  <div className="flex items-center justify-between gap-4">
                    <span className="text-slate-500">
                      {t("mcpTools.detail.website")}
                    </span>
                    <a
                      href={websiteUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="max-w-[70%] truncate font-medium text-sky-700 hover:text-sky-800"
                    >
                      {websiteUrl}
                    </a>
                  </div>
                ) : null}
                {repositoryUrl ? (
                  <div className="flex items-center justify-between gap-4">
                    <span className="text-slate-500">
                      {t("mcpTools.detail.repository")}
                    </span>
                    <a
                      href={repositoryUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="max-w-[70%] truncate font-medium text-sky-700 hover:text-sky-800"
                    >
                      {repositoryUrl}
                    </a>
                  </div>
                ) : null}
              </div>
            </div>

            {(service.tags || []).length > 0 ? (
              <div className={sectionCard}>
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                  {t("mcpTools.detail.tags")}
                </p>
                <div className="mt-2 flex min-h-0 shrink-0 flex-wrap gap-1">
                  {(service.tags || []).map((tag) => (
                    <Tag key={`${service.name}-${tag}`} className="m-0">
                      {tag}
                    </Tag>
                  ))}
                </div>
              </div>
            ) : null}
       

            <div className="flex items-center justify-between gap-3 rounded-xl border border-slate-200/90 bg-white px-4 py-3 shadow-sm">
              <span className="text-sm text-slate-500">
                {t("mcpTools.detail.tools")}
              </span>
              <div className="flex items-center gap-2">
                {hasServerJson ? (
                  <Button
                    size="small"
                    className="rounded-md"
                    autoInsertSpace={false}
                    onClick={() => setShowServerJsonModal(true)}
                  >
                    {t("mcpTools.community.viewServerJson")}
                  </Button>
                ) : null}
                {hasConfigJson ? (
                  <Button
                    size="small"
                    className="rounded-md"
                    autoInsertSpace={false}
                    onClick={() => setShowConfigJsonModal(true)}
                  >
                    {t("mcpTools.detail.viewConfigJson")}
                  </Button>
                ) : null}
              </div>
            </div>
          </div>

          <div className="flex items-center justify-end gap-3 border-t border-slate-200/80 bg-white px-5 py-3.5">
            <Button
              type="primary"
              className="rounded-md"
              onClick={() => onQuickAdd(service)}
            >
              {t("mcpTools.community.quickAdd")}
            </Button>
          </div>
        </div>
      </Modal>

      <JsonPreviewModal
        open={showServerJsonModal && hasServerJson}
        title={t("mcpTools.community.serverJsonTitle", { name: service.name })}
        json={serverJsonPretty}
        onCancel={() => setShowServerJsonModal(false)}
      />

      <JsonPreviewModal
        open={showConfigJsonModal && hasConfigJson}
        title={t("mcpTools.detail.configJsonTitle", { name: service.name })}
        json={configJsonPretty}
        onCancel={() => setShowConfigJsonModal(false)}
      />
    </>
  );
}

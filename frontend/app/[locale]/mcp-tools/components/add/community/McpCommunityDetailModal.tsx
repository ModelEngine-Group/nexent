import { useState } from "react";
import { Button, Modal } from "antd";
import { useTranslation } from "react-i18next";
import {
  Zap,
  Globe,
  GitFork,
  Link,
  Wrench,
  Calendar,
  Server,
  Tag as TagIcon,
  FileText,
} from "lucide-react";
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
import TransportIcon from "../../shared/TransportIcon";

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
        width={620}
        style={{ top: 20 }}
        onCancel={onClose}
        wrapClassName={`${MCP_TOOLS_MODAL_WRAP_CLASS}`}
        styles={mcpToolsModalChromeStyles()}
      >
        <div className="bg-gradient-to-b from-slate-50 to-white">
          {/* Header */}
          <div className="border-b border-slate-200/60 bg-white px-6 py-5">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-3">
                  <TransportIcon
                    transportType={service.transportType}
                    label={service.transportType}
                    className="!h-10 !w-10"
                  />
                  <div className="flex items-center gap-2 min-w-0">
                    <h2 className="text-xl font-semibold tracking-tight text-slate-900 truncate">
                      {service.name}
                    </h2>
                  </div>
                </div>
                <p className="mt-1.5 text-sm text-slate-500 truncate">
                  <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500 mr-1">
                    {service.version ? formatRegistryVersion(service.version) : "v1.0.0"}
                  </span>
                  {service.description || t("mcpTools.detail.noDescription")}
                </p>
              </div>
            </div>
          </div>

          {/* Content */}
          <div className="px-6 py-5 space-y-5">
            {/* Service Info Section */}
            <section className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-sm">
              <h3 className="flex items-center gap-2 text-sm font-medium text-slate-700 mb-4">
                <Zap className="h-4 w-4 text-slate-400" />
                {t("mcpTools.detail.serviceStatus")}
              </h3>
              <div className="space-y-3">
                <InfoRow
                  icon={<GitFork className="h-3.5 w-3.5" />}
                  label={t("mcpTools.detail.serverType")}
                  value={serverTypeText}
                />
                <InfoRow
                  icon={<Calendar className="h-3.5 w-3.5" />}
                  label={t("mcpTools.community.publishedAt")}
                  value={formatRegistryDate(service.createdAt)}
                />
                {service.updatedAt ? (
                  <InfoRow
                    icon={<Calendar className="h-3.5 w-3.5" />}
                    label={t("mcpTools.detail.updatedAt")}
                    value={formatRegistryDate(service.updatedAt)}
                  />
                ) : null}
                <InfoRow
                  icon={<Zap className="h-3.5 w-3.5" />}
                  label={t("mcpTools.detail.status")}
                  customValue={<RegistryStatusBadge status={service.status} />}
                />
              </div>
            </section>

            {/* Server URL Section */}
            {!service.configJson && (
              <section className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-sm">
                <h3 className="flex items-center gap-2 text-sm font-medium text-slate-700 mb-4">
                  <Link className="h-4 w-4 text-slate-400" />
                  {t("mcpTools.detail.serverUrl")}
                </h3>
                <div className="text-sm text-slate-700 font-medium py-1.5 px-3 bg-slate-50 rounded-lg break-all">
                  {service.serverUrl || "-"}
                </div>
              </section>
            )}

            {/* Links Section */}
            {(websiteUrl || repositoryUrl) && (
              <section className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-sm">
                <h3 className="flex items-center gap-2 text-sm font-medium text-slate-700 mb-4">
                  <Link className="h-4 w-4 text-slate-400" />
                  {t("mcpTools.detail.links")}
                </h3>
                <div className="space-y-2">
                  {websiteUrl && (
                    <LinkRow
                      icon={<Globe className="h-3.5 w-3.5" />}
                      label={t("mcpTools.detail.website")}
                      href={websiteUrl}
                    />
                  )}
                  {repositoryUrl && (
                    <LinkRow
                      icon={<GitFork className="h-3.5 w-3.5" />}
                      label={t("mcpTools.detail.repository")}
                      href={repositoryUrl}
                    />
                  )}
                </div>
              </section>
            )}

            {/* Tools Section */}
            {(hasServerJson || hasConfigJson) && (
              <section className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-sm">
                <h3 className="flex items-center gap-2 text-sm font-medium text-slate-700 mb-4">
                  <Wrench className="h-4 w-4 text-slate-400" />
                  {t("mcpTools.detail.tools")}
                </h3>
                <div className="flex flex-wrap gap-2">
                  {hasServerJson && (
                    <Button
                      size="small"
                      autoInsertSpace={false}
                      onClick={() => setShowServerJsonModal(true)}
                      icon={<FileText className="h-3.5 w-3.5" />}
                    >
                      {t("mcpTools.community.viewServerJson")}
                    </Button>
                  )}
                  {hasConfigJson && (
                    <Button
                      size="small"
                      autoInsertSpace={false}
                      onClick={() => setShowConfigJsonModal(true)}
                      icon={<FileText className="h-3.5 w-3.5" />}
                    >
                      {t("mcpTools.detail.viewConfigJson")}
                    </Button>
                  )}
                </div>
              </section>
            )}

            {/* Tags Section */}
            {(service.tags || []).length > 0 && (
              <section className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-sm">
                <h3 className="flex items-center gap-2 text-sm font-medium text-slate-700 mb-4">
                  <TagIcon className="h-4 w-4 text-slate-400" />
                  {t("mcpTools.detail.tags")}
                </h3>
                <div className="flex min-h-0 shrink-0 flex-wrap gap-1.5">
                  {(service.tags || []).map((tag) => (
                    <span
                      key={`${service.name}-${tag}`}
                      className="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-700"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </section>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-3 border-t border-slate-200/60 bg-white px-6 py-4">
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

interface InfoRowProps {
  icon: React.ReactNode;
  label: string;
  value?: string;
  customValue?: React.ReactNode;
}

function InfoRow({ icon, label, value, customValue }: InfoRowProps) {
  return (
    <div className="flex items-center justify-between py-1.5">
      <div className="flex items-center gap-2 text-slate-500">
        {icon}
        <span className="text-sm">{label}</span>
      </div>
      {customValue ? (
        customValue
      ) : (
        <span className="text-sm font-medium text-slate-700">
          {value}
        </span>
      )}
    </div>
  );
}

interface LinkRowProps {
  icon: React.ReactNode;
  label: string;
  href: string;
}

function LinkRow({ icon, label, href }: LinkRowProps) {
  return (
    <div className="flex items-center justify-between py-1.5">
      <div className="flex items-center gap-2 text-slate-500">
        {icon}
        <span className="text-sm">{label}</span>
      </div>
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        className="flex items-center gap-1 text-sm font-medium text-sky-600 hover:text-sky-700"
      >
        <span className="max-w-[200px] truncate">{href.replace(/^https?:\/\//, "")}</span>
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="shrink-0"
        >
          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
          <polyline points="15 3 21 3 21 9" />
          <line x1="10" y1="14" x2="21" y2="3" />
        </svg>
      </a>
    </div>
  );
}

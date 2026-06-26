import { useEffect, useState } from "react";
import { App, Button, Form, Input, Modal } from "antd";
import { useTranslation } from "react-i18next";
import {
  Globe,
  GitFork,
  Link,
  Zap,
  Wrench,
  Calendar,
  Activity,
  Server,
  Tag as TagIcon,
  Pencil,
  Save,
  X,
  FileText,
  Trash2,
} from "lucide-react";
import {
  MCP_TOOLS_MODAL_WRAP_CLASS,
  mcpToolsModalChromeStyles,
} from "@/const/mcpTools";
import type { CommunityMcpCard } from "@/types/mcpTools";
import { useMcpFormRules } from "@/hooks/mcpTools/useMcpFormRules";
import { usePublishedServiceDetailEdit } from "@/hooks/mcpTools/usePublishedServiceDetailEdit";
import {
  extractRegistryLinks,
  formatRegistryDate,
  getTransportLabelKey,
  toPrettyRegistryJson,
} from "@/lib/mcpTools";
import TransportIcon from "./shared/TransportIcon";
import JsonPreviewModal from "./shared/JsonPreviewModal";
import TagEditor from "./shared/TagEditor";

interface PublishedServiceDetailModalProps {
  open: boolean;
  service: CommunityMcpCard | null;
  onClose: () => void;
}

/**
 * Editable detail modal for the "my published" tab. Mirrors the layout of
 * {@link McpServiceDetailModal} with a rich header, sectioned content,
 * and inline edit mode for name/description. Version and tags remain editable.
 */
export default function PublishedServiceDetailModal({
  open,
  service,
  onClose,
}: PublishedServiceDetailModalProps) {
  const { t } = useTranslation("common");
  const { modal } = App.useApp();
  const rules = useMcpFormRules();
  const [form] = Form.useForm();
  const [isEditing, setIsEditing] = useState(false);
  const edit = usePublishedServiceDetailEdit(service, open);
  const { draft, saving, deleting, updateDraft, addDraftTag, removeDraftTag } =
    edit;
  const [showServerJsonModal, setShowServerJsonModal] = useState(false);
  const [showConfigJsonModal, setShowConfigJsonModal] = useState(false);

  const { websiteUrl, repositoryUrl } = extractRegistryLinks(
    (service?.registryJson || undefined) as Record<string, unknown> | undefined
  );
  const serverJsonPretty = toPrettyRegistryJson(
    (service?.registryJson || undefined) as Record<string, unknown> | undefined
  );
  const configJsonPretty = toPrettyRegistryJson(
    (service?.configJson || undefined) as Record<string, unknown> | undefined
  );
  const hasServerJson = Boolean(
    service?.registryJson && Object.keys(service.registryJson).length > 0
  );
  const hasConfigJson = Boolean(
    service?.configJson && Object.keys(service.configJson).length > 0
  );

  useEffect(() => {
    if (!open) {
      setShowServerJsonModal(false);
      setShowConfigJsonModal(false);
      setIsEditing(false);
    }
  }, [open]);

  useEffect(() => {
    if (!open || !draft) return;
    form.setFieldsValue({
      name: draft.name,
      description: draft.description,
      version: draft.version,
    });
  }, [open, draft, form]);

  const handleStartEdit = () => {
    if (!draft) return;
    form.setFieldsValue({
      name: draft.name,
      description: draft.description,
      version: draft.version,
    });
    setIsEditing(true);
  };

  const handleCancelEdit = () => {
    if (!draft) return;
    form.setFieldsValue({
      name: draft.name,
      description: draft.description,
      version: draft.version,
    });
    setIsEditing(false);
  };

  const handleSave = async () => {
    try {
      await form.validateFields();
    } catch {
      return;
    }
    // Sync form values to draft before saving
    const values = form.getFieldsValue();
    edit.updateDraft({
      name: values.name ?? "",
      description: values.description ?? "",
      version: values.version ?? "",
    });
    const ok = await edit.save();
    if (ok) {
      setIsEditing(false);
      onClose();
    }
  };

  const handleDelete = () => {
    if (!service?.communityId) return;
    modal.confirm({
      title: t("mcpTools.community.mine.unpublishTitle"),
      centered: true,
      content: (
        <p className="text-sm text-slate-600 break-all">{service.name}</p>
      ),
      okText: t("mcpTools.community.mine.unpublishConfirm"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      onOk: async () => {
        if (typeof service.communityId !== "number") return;
        const ok = await edit.remove(service.communityId);
        if (ok) onClose();
      },
    });
  };

  if (!service || !draft) return null;

  return (
    <>
      <Modal
        open={open}
        footer={null}
        closable
        centered
        width={620}
        style={{ top: 20 }}
        onCancel={() => {
          setIsEditing(false);
          onClose();
        }}
        wrapClassName={`${MCP_TOOLS_MODAL_WRAP_CLASS} h-[calc(100dvh-80px)]`}
        styles={mcpToolsModalChromeStyles()}
      >
        <Form form={form} className="bg-gradient-to-b from-slate-50 to-white">
          {/* Header */}
          <div className="border-b border-slate-200/60 bg-white px-6 py-5">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0 flex-1">
                <div className="min-h-[60px]">
                  {isEditing ? (
                    <div className="space-y-2">
                      <Form.Item name="name" className="mb-0" rules={rules.name}>
                        <Input
                          className="rounded-lg font-semibold text-lg"
                          placeholder={t("mcpTools.detail.name")}
                        />
                      </Form.Item>
                      <div className="flex items-center gap-2">
                        <span className="text-sm text-slate-500 font-medium">v</span>
                        <Form.Item name="version" className="mb-0 w-16" rules={rules.version}>
                          <Input.TextArea
                            className="rounded-lg resize-none overflow-y-auto max-h-20"
                            placeholder="1.0.0"
                            autoSize={{ minRows: 1, maxRows: 1 }}
                          />
                        </Form.Item>
                        <Form.Item name="description" className="mb-0 flex-1" rules={rules.description}>
                          <Input.TextArea
                            className="rounded-lg resize-none overflow-y-auto max-h-20"
                            placeholder={t("mcpTools.detail.description")}
                            autoSize={{ minRows: 1, maxRows: 1 }}
                          />
                        </Form.Item>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div className="flex items-center gap-3">
                        <TransportIcon
                          transportType={service.transportType}
                          label={service.transportType}
                          className="!h-10 !w-10"
                        />
                        <div className="flex items-center gap-2 min-w-0">
                          <h2 className="text-xl font-semibold tracking-tight text-slate-900 truncate">
                            {draft.name}
                          </h2>
                        </div>
                      </div>
                      <p className="mt-1.5 text-sm text-slate-500 truncate">
                        <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500 mr-1">
                          v{draft.version || "1.0.0"}
                        </span>
                        {draft.description || t("mcpTools.detail.noDescription")}
                      </p>
                    </>
                  )}
                </div>
              </div>

              {/* Edit Action Buttons */}
              <div className="flex items-center gap-2 shrink-0">
                {isEditing ? (
                  <>
                    <Button
                      onClick={handleCancelEdit}
                      icon={<X className="h-4 w-4" />}
                    >
                      {t("common.cancel")}
                    </Button>
                    <Button
                      type="primary"
                      loading={saving}
                      onClick={handleSave}
                      icon={<Save className="h-4 w-4" />}
                    >
                      {t("common.save")}
                    </Button>
                  </>
                ) : (
                  <>
                    <Button
                      onClick={handleStartEdit}
                      icon={<Pencil className="h-4 w-4" />}
                    >
                      {t("common.edit")}
                    </Button>
                    <Button
                      onClick={handleDelete}
                      danger
                      loading={deleting}
                      disabled={!service.communityId}
                      icon={<Trash2 className="h-4 w-4" />}
                    />
                  </>
                )}
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
                  value={t(getTransportLabelKey(service.transportType))}
                />
                <InfoRow
                  icon={<Calendar className="h-3.5 w-3.5" />}
                  label={t("mcpTools.detail.createdAt")}
                  value={formatRegistryDate(service.createdAt)}
                />
                {service.updatedAt ? (
                  <InfoRow
                    icon={<Calendar className="h-3.5 w-3.5" />}
                    label={t("mcpTools.detail.updatedAt")}
                    value={formatRegistryDate(service.updatedAt)}
                  />
                ) : null}
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
            <section className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-sm">
              <h3 className="flex items-center gap-2 text-sm font-medium text-slate-700 mb-4">
                <TagIcon className="h-4 w-4 text-slate-400" />
                {t("mcpTools.detail.tags")}
              </h3>
              <TagEditor
                tags={draft.tags ?? []}
                onAddTag={(tag) => addDraftTag((tag || "").trim())}
                onRemoveTag={removeDraftTag}
                removeAriaKey="mcpTools.detail.removeTagAria"
                placeholderKey="mcpTools.detail.tagInputPlaceholder"
                loading={edit.tagSaving}
              />
            </section>
          </div>
        </Form>
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
  value: string;
  customValue?: React.ReactNode;
  valueClass?: string;
}

function InfoRow({ icon, label, value, customValue, valueClass }: InfoRowProps) {
  return (
    <div className="flex items-center justify-between py-1.5">
      <div className="flex items-center gap-2 text-slate-500">
        {icon}
        <span className="text-sm">{label}</span>
      </div>
      {customValue ? (
        <span className={valueClass}>{customValue}</span>
      ) : (
        <span className={`text-sm font-medium ${valueClass || "text-slate-700"}`}>
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

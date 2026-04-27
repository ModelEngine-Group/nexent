import { useEffect, useState } from "react";
import { App, Button, Form, Input, Modal } from "antd";
import { useTranslation } from "react-i18next";
import type { CommunityMcpCard } from "@/types/mcpTools";
import type { MyCommunityEditDraft } from "@/hooks/mcpTools/useMyCommunityMcp";
import { useMcpFormRules } from "@/hooks/mcpTools/useMcpFormRules";
import {
  extractRegistryLinks,
  formatRegistryDate,
  getTransportLabelKey,
  toPrettyRegistryJson,
} from "@/lib/mcpTools";
import RegistryStatusBadge from "./shared/StatusBadge";
import JsonPreviewModal from "./shared/JsonPreviewModal";
import TagEditor from "./shared/TagEditor";

interface PublishedServiceDetailModalProps {
  open: boolean;
  service: CommunityMcpCard | null;
  draft: MyCommunityEditDraft | null;
  saving: boolean;
  deleting: boolean;
  onCancel: () => void;
  onChange: (patch: Partial<MyCommunityEditDraft>) => void;
  onAddTag: (tag: string) => void;
  onRemoveTag: (index: number) => void;
  onSave: () => Promise<boolean | void> | void;
  onDelete: () => Promise<void> | void;
}

/**
 * Editable detail for the "my published" tab. Read-only block mirrors
 * {@link McpCommunityDetailModal} (URL, source, type, status, times, links,
 * JSON); name / description / version / tags stay editable and persist via the
 * parent draft + save.
 */
export default function PublishedServiceDetailModal({
  open,
  service,
  draft,
  saving,
  deleting,
  onCancel,
  onChange,
  onAddTag,
  onRemoveTag,
  onSave,
  onDelete,
}: PublishedServiceDetailModalProps) {
  const { t } = useTranslation("common");
  const { modal } = App.useApp();
  const rules = useMcpFormRules();
  const [form] = Form.useForm();
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

  const serverTypeText = service
    ? t(getTransportLabelKey(service.transportType))
    : "";

  useEffect(() => {
    if (!open) {
      setShowServerJsonModal(false);
      setShowConfigJsonModal(false);
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

  const handleSave = async () => {
    try {
      await form.validateFields();
    } catch {
      return;
    }
    await onSave();
  };

  const handleDelete = () => {
    if (!service?.communityId) return;
    modal.confirm({
      title: t("mcpTools.delete.confirmTitle"),
      content: (
        <div className="space-y-1">
          <p className="text-sm text-slate-600 break-all">{service.name}</p>
          <p className="text-xs text-slate-400">
            {t("mcpTools.delete.confirmDesc")}
          </p>
        </div>
      ),
      okText: t("mcpTools.delete.confirmOk"),
      cancelText: t("mcpTools.delete.confirmCancel"),
      okButtonProps: { danger: true },
      onOk: () => onDelete(),
    });
  };

  if (!service) return null;

  return (
    <>
      <Modal
        open={open}
        onCancel={onCancel}
        footer={null}
        width={900}
        centered
        title={t("mcpTools.published.detailTitle")}
        destroyOnHidden
        styles={{ mask: { background: "rgba(15,23,42,0.4)" } }}
      >
        <div className="max-h-[min(85vh,900px)] overflow-y-auto pr-0.5">
          <Form
            form={form}
            layout="vertical"
            requiredMark={false}
            className="space-y-3"
          >
            <Form.Item
              label={t("mcpTools.detail.name")}
              name="name"
              rules={rules.name}
            >
              <Input
                value={draft?.name ?? ""}
                onChange={(event) => {
                  onChange({ name: event.target.value });
                  form.setFieldValue("name", event.target.value);
                }}
                className="rounded-md"
              />
            </Form.Item>

            <Form.Item
              label={t("mcpTools.detail.description")}
              name="description"
              rules={rules.description}
            >
              <Input.TextArea
                value={draft?.description ?? ""}
                onChange={(event) => {
                  onChange({ description: event.target.value });
                  form.setFieldValue("description", event.target.value);
                }}
                autoSize={{ minRows: 2, maxRows: 16 }}
                className="rounded-md"
              />
            </Form.Item>

          <div className="space-y-5 border-b border-slate-100 py-5">
            { !service.configJson ? <div>
              <p className="text-sm text-slate-500">
                {t("mcpTools.detail.serverUrl")}
              </p>
              <p className="mt-1 break-all rounded-md border border-slate-200 bg-slate-50 px-4 py-2 text-sm font-medium text-slate-800">
                {service.serverUrl}
              </p>
            </div> : null }

            <div className="grid gap-3 text-sm text-slate-700">
              <div className="flex items-center justify-between">
                <span className="text-slate-500">
                  {t("mcpTools.detail.serverType")}
                </span>
                <span className="font-medium text-slate-800">
                  {serverTypeText}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-500">
                  {t("mcpTools.detail.status")}
                </span>
                <RegistryStatusBadge
                  status={service.status}
                  className="px-3 py-1 text-xs"
                />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-500">
                  {t("mcpTools.detail.createdAt")}
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

            <div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-slate-500">
                  {t("mcpTools.detail.tools")}
                </span>
                <div className="flex flex-wrap items-center justify-end gap-2">
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
          </div>

            <Form.Item
              className="pt-2"
              label={t("mcpTools.detail.version")}
              name="version"
              rules={rules.version}
            >
              <Input
                value={draft?.version ?? ""}
                onChange={(event) => {
                  onChange({ version: event.target.value });
                  form.setFieldValue("version", event.target.value);
                }}
                placeholder="1.0.0"
                className="rounded-md"
              />
            </Form.Item>

            <TagEditor
              title={t("mcpTools.detail.tags")}
              tags={draft?.tags ?? []}
              onAddTag={(tag) => onAddTag((tag || "").trim())}
              onRemoveTag={onRemoveTag}
              removeAriaKey="mcpTools.detail.removeTagAria"
            />
          </Form>

          <div className="mt-5 flex items-center justify-end gap-2 border-t border-slate-100 pt-4">
            <Button
              danger
              loading={deleting}
              disabled={!service.communityId}
              onClick={handleDelete}
            >
              {t("common.delete")}
            </Button>
            <Button type="primary" loading={saving} onClick={handleSave}>
              {t("common.save")}
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

import { useEffect, useState } from "react";
import { Form, Input, Modal } from "antd";
import { useTranslation } from "react-i18next";
import { McpTransportType } from "@/const/mcpTools";
import type { McpServiceItem } from "@/types/mcpTools";
import { useMcpFormRules } from "@/hooks/mcpTools/useMcpFormRules";
import TagEditor from "./shared/TagEditor";

export interface PublishOverride {
  name: string;
  description: string;
  version: string;
  tags: string[];
  /** Remote server URL; only used when publishing a URL-type MCP. */
  serverUrl: string;
  /** Container config JSON text; only used when publishing a container MCP. */
  containerConfigJson?: string;
}

interface PublishConfirmModalProps {
  open: boolean;
  source: McpServiceItem | null;
  publishing: boolean;
  onCancel: () => void;
  onConfirm: (override: PublishOverride) => Promise<boolean | void> | void;
}

/**
 * Confirmation step for "publish to community". Owns its own draft so the
 * source service is never mutated; only the published copy reflects edits.
 */
export default function PublishConfirmModal({
  open,
  source,
  publishing,
  onCancel,
  onConfirm,
}: PublishConfirmModalProps) {
  const { t } = useTranslation("common");
  const rules = useMcpFormRules();
  const [form] = Form.useForm();
  const [draft, setDraft] = useState<PublishOverride>({
    name: "",
    description: "",
    version: "",
    tags: [],
    serverUrl: "",
    containerConfigJson: "",
  });

  useEffect(() => {
    if (!open || !source) return;
    const containerConfigJson =
      source.transportType === McpTransportType.CONTAINER
        ? JSON.stringify(source.configJson ?? {}, null, 2)
        : "";
    const next: PublishOverride = {
      name: source.name,
      description: source.description,
      version: source.version || "",
      tags: source.tags || [],
      serverUrl: source.serverUrl || "",
      containerConfigJson,
    };
    setDraft(next);
    form.setFieldsValue(next);
  }, [open, source, form]);

  const patch = (partial: Partial<PublishOverride>) => {
    setDraft((prev) => ({ ...prev, ...partial }));
  };

  const handleOk = async () => {
    if (!source) return;
    try {
      await form.validateFields();
    } catch {
      return;
    }
    await onConfirm({
      name: draft.name.trim(),
      description: draft.description,
      version: draft.version.trim(),
      tags: draft.tags,
      serverUrl:
        source?.transportType !== McpTransportType.CONTAINER
          ? draft.serverUrl.trim()
          : "",
      containerConfigJson:
        source?.transportType === McpTransportType.CONTAINER
          ? draft.containerConfigJson?.trim() ?? ""
          : undefined,
    });
  };

  return (
    <Modal
      open={open}
      title={t("mcpTools.publish.confirmTitle")}
      onCancel={onCancel}
      onOk={handleOk}
      okText={t("mcpTools.community.publish")}
      cancelText={t("common.cancel")}
      confirmLoading={publishing}
      width={560}
      centered
      destroyOnHidden
    >
      <p className="mb-3 text-xs text-slate-500">
        {t("mcpTools.publish.confirmHint")}
      </p>
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
            value={draft.name}
            onChange={(event) => {
              patch({ name: event.target.value });
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
            value={draft.description}
            onChange={(event) => {
              patch({ description: event.target.value });
              form.setFieldValue("description", event.target.value);
            }}
            autoSize={{ minRows: 2, maxRows: 12 }}
            className="rounded-md"
          />
        </Form.Item>

        <Form.Item
          label={t("mcpTools.detail.version")}
          name="version"
          rules={rules.version}
        >
          <Input
            value={draft.version}
            onChange={(event) => {
              patch({ version: event.target.value });
              form.setFieldValue("version", event.target.value);
            }}
            placeholder="1.0.0"
            className="rounded-md"
          />
        </Form.Item>

        {source?.transportType !== McpTransportType.CONTAINER ? (
          <Form.Item
            label={t("mcpTools.detail.serverUrl")}
            name="serverUrl"
            rules={rules.httpUrl}
          >
            <Input
              value={draft.serverUrl}
              onChange={(event) => {
                patch({ serverUrl: event.target.value });
                form.setFieldValue("serverUrl", event.target.value);
              }}
              className="rounded-md"
            />
          </Form.Item>
        ) : null}

        {source?.transportType === McpTransportType.CONTAINER ? (
          <Form.Item
            label={t("mcpTools.addModal.containerConfig")}
            name="containerConfigJson"
            rules={rules.containerConfig}
            className="mb-0 text-sm text-slate-500"
          >
            <Input.TextArea
              value={draft.containerConfigJson ?? ""}
              onChange={(event) => {
                patch({ containerConfigJson: event.target.value });
                form.setFieldValue("containerConfigJson", event.target.value);
              }}
              rows={6}
              className="mt-2 rounded-md font-mono text-sm"
              placeholder={t("mcpTools.addModal.containerConfigPlaceholder")}
            />
          </Form.Item>
        ) : null}

        <TagEditor
          title={t("mcpTools.detail.tags")}
          tags={draft.tags}
          onAddTag={(tag) => {
            const next = (tag || "").trim();
            if (!next || draft.tags.includes(next)) return;
            patch({ tags: [...draft.tags, next] });
          }}
          onRemoveTag={(index) =>
            patch({ tags: draft.tags.filter((_, i) => i !== index) })
          }
          removeAriaKey="mcpTools.detail.removeTagAria"
        />
      </Form>
    </Modal>
  );
}

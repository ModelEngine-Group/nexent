import { useState } from "react";
import { Button, Form, Input, Select } from "antd";
import { useTranslation } from "react-i18next";
import {
  MCP_ADD_SERVICE_LOCAL_SECTION_WIDTH_PX,
  McpTransportType,
} from "@/const/mcpTools";
import type { LocalAddMcpDraft } from "@/types/mcpTools";
import { useMcpAddLocal } from "@/hooks/mcpTools/useMcpAddLocal";
import { useMcpFormRules } from "@/hooks/mcpTools/useMcpFormRules";
import ContainerPortField from "./shared/ContainerPortField";
import TagEditor from "./shared/TagEditor";

const createInitialDraft = (): LocalAddMcpDraft => ({
  name: "",
  description: "",
  transportType: McpTransportType.URL,
  serverUrl: "",
  authorizationToken: "",
  containerConfigJson: "",
  containerPort: undefined,
  tags: [],
});

interface AddMcpServiceLocalSectionProps {
  active: boolean;
  onAdded: () => void;
}

export default function AddMcpServiceLocalSection({
  active,
  onAdded,
}: AddMcpServiceLocalSectionProps) {
  const { t } = useTranslation("common");
  const rules = useMcpFormRules();
  const [form] = Form.useForm();
  const [draft, setDraft] = useState<LocalAddMcpDraft>(() => createInitialDraft());
  const { submit, submitting } = useMcpAddLocal({
    onSuccess: () => {
      setDraft(createInitialDraft());
      form.resetFields();
      onAdded();
    },
  });

  const patchDraft = (patch: Partial<LocalAddMcpDraft>) => {
    setDraft((prev) => ({ ...prev, ...patch }));
  };

  // Syncs external `draft` into AntD Form state so validation sees the value.
  const bindField = <K extends keyof LocalAddMcpDraft>(key: K) => ({
    value: draft[key],
    onChange: (eventOrValue: unknown) => {
      const next =
        eventOrValue &&
        typeof eventOrValue === "object" &&
        "target" in (eventOrValue as Record<string, unknown>)
          ? (eventOrValue as { target: { value: LocalAddMcpDraft[K] } }).target
              .value
          : (eventOrValue as LocalAddMcpDraft[K]);
      patchDraft({ [key]: next } as Partial<LocalAddMcpDraft>);
      form.setFieldValue(key as string, next);
    },
  });

  const addTag = (tag: string) => {
    const next = (tag || "").trim();
    if (!next || draft.tags.includes(next)) return;
    patchDraft({ tags: [...draft.tags, next] });
  };

  const removeTag = (index: number) => {
    patchDraft({ tags: draft.tags.filter((_, i) => i !== index) });
  };

  const handleSubmit = async () => {
    try {
      await form.validateFields();
    } catch {
      return;
    }
    await submit(draft);
  };

  if (!active) return null;

  const isHttpLike = draft.transportType !== McpTransportType.CONTAINER;

  return (
    <div
      className="mx-auto w-full"
      style={{ maxWidth: MCP_ADD_SERVICE_LOCAL_SECTION_WIDTH_PX }}
    >
      <Form
        form={form}
        layout="vertical"
        requiredMark={false}
        className="space-y-4 px-6 py-5"
      >
        <Form.Item
          label={t("mcpTools.addModal.name")}
          name="name"
          className="mb-0 text-sm text-slate-500"
          rules={rules.name}
        >
          <Input {...bindField("name")} className="mt-2 w-full rounded-md" />
        </Form.Item>

        <Form.Item
          label={t("mcpTools.addModal.description")}
          name="description"
          className="mb-0 text-sm text-slate-500"
          rules={rules.description}
        >
          <Input.TextArea
            {...bindField("description")}
            autoSize={{ minRows: 1, maxRows: 20 }}
            className="mt-2 w-full rounded-md"
          />
        </Form.Item>

        <Form.Item
          label={t("mcpTools.addModal.serverType")}
          name="transportType"
          initialValue={draft.transportType}
          className="mb-0 text-sm text-slate-500"
          rules={rules.transportType}
        >
          <Select
            value={draft.transportType}
            onChange={(value: McpTransportType) => {
              patchDraft({ transportType: value });
              form.setFieldValue("transportType", value);
            }}
            className="mt-2 w-full"
            options={[
              {
                label: t("mcpTools.serverType.url"),
                value: McpTransportType.URL,
              },
              {
                label: t("mcpTools.serverType.container"),
                value: McpTransportType.CONTAINER,
              },
            ]}
          />
        </Form.Item>

        {isHttpLike ? (
          <div className="space-y-4">
            <Form.Item
              label={t("mcpTools.addModal.serverUrl")}
              name="serverUrl"
              className="mb-0 text-sm text-slate-500"
              rules={rules.httpUrl}
            >
              <Input
                {...bindField("serverUrl")}
                className="mt-2 w-full rounded-md"
                placeholder={t("mcpTools.addModal.serverUrl")}
              />
            </Form.Item>
            <Form.Item
              label={t("mcpTools.addModal.bearerTokenOptional")}
              name="authorizationToken"
              className="mb-0 text-sm text-slate-500"
              rules={rules.authToken}
            >
              <Input
                {...bindField("authorizationToken")}
                className="mt-2 w-full rounded-md"
                placeholder={t("mcpTools.addModal.bearerTokenPlaceholder")}
              />
            </Form.Item>
          </div>
        ) : (
          <div className="space-y-4 rounded-md border border-slate-200 bg-slate-50 p-4">
            <Form.Item
              label={t("mcpTools.addModal.containerConfig")}
              name="containerConfigJson"
              className="mb-0 text-sm text-slate-500"
              rules={rules.containerConfig}
            >
              <Input.TextArea
                {...bindField("containerConfigJson")}
                rows={5}
                placeholder={t("mcpTools.addModal.containerConfigPlaceholder")}
                className="mt-2"
              />
            </Form.Item>

            <Form.Item
              name="containerPort"
              className="mb-0"
              rules={rules.containerPort}
            >
              <div>
                <ContainerPortField
                  scope="local"
                  containerPort={draft.containerPort}
                  setContainerPort={(value) => {
                    patchDraft({ containerPort: value });
                    form.setFieldValue("containerPort", value);
                  }}
                />
              </div>
            </Form.Item>
          </div>
        )}

        <TagEditor
          title={t("mcpTools.addModal.tags")}
          tags={draft.tags}
          onAddTag={(tag) => addTag(tag || "")}
          onRemoveTag={removeTag}
        />
      </Form>

      <div className="flex items-center justify-end gap-3 border-t border-slate-100 px-6 py-4">
        <Button type="primary" onClick={handleSubmit} loading={submitting}>
          {t("mcpTools.addModal.saveAndAdd")}
        </Button>
      </div>
    </div>
  );
}

import { useState } from "react";
import { Button, Form, Input, Select } from "antd";
import { useTranslation } from "react-i18next";
import { INITIAL_LOCAL_ADD_DRAFT, MCP_TRANSPORT_TYPE } from "@/const/mcpTools";
import type { LocalAddMcpDraft, McpTransportType } from "@/types/mcpTools";
import { useMcpAddLocal } from "@/hooks/mcpTools/useMcpAddLocal";
import { useMcpFormRules } from "@/hooks/mcpTools/useMcpFormRules";
import ContainerPortField from "./ContainerPortField";
import TagEditor from "./shared/TagEditor";

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
  const [draft, setDraft] = useState<LocalAddMcpDraft>(INITIAL_LOCAL_ADD_DRAFT);
  const [tagInput, setTagInput] = useState("");
  const { submit, submitting } = useMcpAddLocal({
    onSuccess: () => {
      setDraft(INITIAL_LOCAL_ADD_DRAFT);
      setTagInput("");
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

  const addTag = () => {
    const next = tagInput.trim();
    setTagInput("");
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

  const isHttpLike =
    draft.transportType === MCP_TRANSPORT_TYPE.HTTP ||
    draft.transportType === MCP_TRANSPORT_TYPE.SSE;

  return (
    <>
      <Form
        form={form}
        layout="vertical"
        requiredMark={false}
        className="px-6 py-5 space-y-4"
      >
        <Form.Item
          label={t("mcpTools.addModal.name")}
          name="name"
          className="mb-0 text-sm text-slate-500"
          rules={rules.name}
        >
          <Input {...bindField("name")} className="mt-2 w-full rounded-2xl" />
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
            className="mt-2 w-full rounded-2xl"
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
                label: t("mcpTools.serverType.http"),
                value: MCP_TRANSPORT_TYPE.HTTP,
              },
              {
                label: t("mcpTools.serverType.sse"),
                value: MCP_TRANSPORT_TYPE.SSE,
              },
              {
                label: t("mcpTools.serverType.container"),
                value: MCP_TRANSPORT_TYPE.CONTAINER,
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
                className="mt-2 w-full rounded-2xl"
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
                className="mt-2 w-full rounded-2xl"
                placeholder={t("mcpTools.addModal.bearerTokenPlaceholder")}
              />
            </Form.Item>
          </div>
        ) : (
          <div className="space-y-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
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
          tagInput={tagInput}
          onTagInputChange={setTagInput}
          onAddTag={addTag}
          onRemoveTag={removeTag}
        />
      </Form>

      <div className="flex items-center justify-end gap-3 border-t border-slate-100 px-6 py-4">
        <Button
          type="primary"
          className="rounded-full"
          onClick={handleSubmit}
          loading={submitting}
        >
          {t("mcpTools.addModal.saveAndAdd")}
        </Button>
      </div>
    </>
  );
}

import { useMemo, useState } from "react";
import { Button, Form, Input, Select, Tag } from "antd";
import { useTranslation } from "react-i18next";
import { MCP_TRANSPORT_TYPE } from "@/const/mcpTools";
import type { LocalAddMcpDraft, McpTransportType } from "@/types/mcpTools";
import { isHttpUrl } from "@/lib/mcpTools";
import { MarkdownRenderer } from "@/components/ui/markdownRenderer";
import { useMcpAddLocal } from "@/hooks/mcpTools/useMcpAddLocal";
import ContainerPortField from "./ContainerPortField";

interface AddMcpServiceLocalSectionProps {
  active: boolean;
  onAdded: () => void;
}

const INITIAL_DRAFT: LocalAddMcpDraft = {
  name: "",
  description: "",
  transportType: MCP_TRANSPORT_TYPE.HTTP,
  serverUrl: "",
  authorizationToken: "",
  containerConfigJson: "",
  containerPort: undefined,
  tags: [],
};

export default function AddMcpServiceLocalSection({
  active,
  onAdded,
}: AddMcpServiceLocalSectionProps) {
  const { t } = useTranslation("common");
  const [form] = Form.useForm();
  const [draft, setDraft] = useState<LocalAddMcpDraft>(INITIAL_DRAFT);
  const [tagInput, setTagInput] = useState("");
  const [descriptionExpanded, setDescriptionExpanded] = useState(false);
  const { submit, submitting } = useMcpAddLocal({
    onSuccess: () => {
      setDraft(INITIAL_DRAFT);
      setTagInput("");
      form.resetFields();
      onAdded();
    },
  });

  const patchDraft = (patch: Partial<LocalAddMcpDraft>) => {
    setDraft((prev) => ({ ...prev, ...patch }));
  };

  const addTag = () => {
    const next = tagInput.trim();
    if (!next) {
      setTagInput("");
      return;
    }
    if (draft.tags.includes(next)) {
      setTagInput("");
      return;
    }
    patchDraft({ tags: [...draft.tags, next] });
    setTagInput("");
  };

  const removeTag = (index: number) => {
    patchDraft({ tags: draft.tags.filter((_, i) => i !== index) });
  };

  const canToggleDescription = useMemo(() => {
    const text = draft.description || "";
    return text.length > 280 || text.split("\n").length > 8;
  }, [draft.description]);

  const handleSubmit = async () => {
    try {
      await form.validateFields();
    } catch {
      return;
    }
    await submit(draft);
  };

  if (!active) return null;

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
          rules={[
            {
              required: true,
              whitespace: true,
              message: t("mcpTools.add.validate.nameRequired"),
            },
            {
              type: "string",
              max: 100,
              message: t("mcpTools.add.validate.nameMaxLength"),
            },
          ]}
        >
          <Input
            value={draft.name}
            onChange={(event) => {
              patchDraft({ name: event.target.value });
              form.setFieldValue("name", event.target.value);
            }}
            className="mt-2 w-full rounded-2xl"
          />
        </Form.Item>

        <Form.Item
          label={t("mcpTools.addModal.description")}
          name="description"
          className="mb-0 text-sm text-slate-500"
          rules={[
            {
              type: "string",
              max: 5000,
              message: t("mcpTools.add.validate.descriptionMaxLength"),
            },
          ]}
        >
          <Input.TextArea
            value={draft.description}
            onChange={(event) => {
              patchDraft({ description: event.target.value });
              form.setFieldValue("description", event.target.value);
            }}
            autoSize={{ minRows: 1, maxRows: 20 }}
            className="mt-2 w-full rounded-2xl"
          />
        </Form.Item>

        <Form.Item
          label={t("mcpTools.addModal.serverType")}
          name="transportType"
          initialValue={draft.transportType}
          className="mb-0 text-sm text-slate-500"
          rules={[
            {
              required: true,
              message: t("mcpTools.add.validate.transportTypeRequired"),
            },
          ]}
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

        {draft.transportType === MCP_TRANSPORT_TYPE.HTTP ||
        draft.transportType === MCP_TRANSPORT_TYPE.SSE ? (
          <div className="space-y-4">
            <Form.Item
              label={t("mcpTools.addModal.serverUrl")}
              name="serverUrl"
              className="mb-0 text-sm text-slate-500"
              rules={[
                {
                  validator: async (_rule, value) => {
                    const text = String(value || "").trim();
                    if (!text)
                      throw new Error(
                        t("mcpTools.add.validate.httpUrlRequired")
                      );
                    if (text.length > 500)
                      throw new Error(
                        t("mcpTools.add.validate.httpUrlMaxLength")
                      );
                    if (!isHttpUrl(text))
                      throw new Error(t("mcpTools.add.validate.httpUrlFormat"));
                  },
                },
              ]}
            >
              <Input
                value={draft.serverUrl}
                onChange={(event) => {
                  patchDraft({ serverUrl: event.target.value });
                  form.setFieldValue("serverUrl", event.target.value);
                }}
                className="mt-2 w-full rounded-2xl"
                placeholder={t("mcpTools.addModal.serverUrl")}
              />
            </Form.Item>
            <Form.Item
              label={t("mcpTools.addModal.bearerTokenOptional")}
              name="authorizationToken"
              className="mb-0 text-sm text-slate-500"
              rules={[
                {
                  type: "string",
                  max: 500,
                  message: t(
                    "mcpTools.add.validate.authorizationTokenMaxLength"
                  ),
                },
              ]}
            >
              <Input
                value={draft.authorizationToken}
                onChange={(event) => {
                  patchDraft({ authorizationToken: event.target.value });
                  form.setFieldValue("authorizationToken", event.target.value);
                }}
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
              rules={[
                {
                  validator: async (_rule, value) => {
                    const text = String(value || "").trim();
                    if (!text)
                      throw new Error(
                        t("mcpTools.add.validate.containerConfigRequired")
                      );
                    try {
                      JSON.parse(text);
                    } catch {
                      throw new Error(
                        t("mcpTools.add.error.containerJsonInvalid")
                      );
                    }
                  },
                },
              ]}
            >
              <Input.TextArea
                value={draft.containerConfigJson}
                onChange={(event) => {
                  patchDraft({ containerConfigJson: event.target.value });
                  form.setFieldValue("containerConfigJson", event.target.value);
                }}
                rows={5}
                placeholder={t("mcpTools.addModal.containerConfigPlaceholder")}
                className="mt-2"
              />
            </Form.Item>

            <Form.Item
              name="containerPort"
              className="mb-0"
              rules={[
                {
                  validator: async (_rule, value) => {
                    if (value === undefined || value === null || value === "") {
                      throw new Error(
                        t("mcpTools.add.validate.containerRequired")
                      );
                    }
                    const port = Number(value);
                    if (!Number.isInteger(port) || port < 1 || port > 65535) {
                      throw new Error(
                        t("mcpTools.add.validate.containerPortRange")
                      );
                    }
                  },
                },
              ]}
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

        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            {t("mcpTools.addModal.tags")}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {draft.tags.map((tag, index) => (
              <span key={`${tag}-${index}`} className="relative inline-flex">
                <Tag className="rounded-full px-3 py-1 m-0 leading-none">
                  {tag}
                </Tag>
                <button
                  type="button"
                  onClick={() => removeTag(index)}
                  className="absolute top-0 right-0 -translate-y-1/2 translate-x-1/2 flex h-4 w-4 items-center justify-center rounded-full bg-slate-200 text-[10px] text-slate-500 transition hover:bg-slate-300 hover:text-slate-700"
                  aria-label={t("mcpTools.addModal.removeTagAria", { tag })}
                >
                  x
                </button>
              </span>
            ))}
            <Input
              size="small"
              value={tagInput}
              onChange={(event) => setTagInput(event.target.value)}
              onPressEnter={addTag}
              onBlur={addTag}
              placeholder={t("mcpTools.addModal.tagInputPlaceholder")}
              className="w-40 rounded-full"
            />
          </div>
        </div>
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

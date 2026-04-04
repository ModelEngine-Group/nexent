import { useEffect, useMemo, useState } from "react";
import { Button, Form, Input, Select, Tag } from "antd";
import { MCP_TRANSPORT_TYPE } from "@/const/mcpTools";
import type { McpTransportType } from "@/types/mcpTools";
import { MarkdownRenderer } from "@/components/ui/markdownRenderer";
import ContainerPortField from "./ContainerPortField";

interface Props {
  newServiceName: string;
  newServiceDesc: string;
  newTransportType: McpTransportType;
  newServiceUrl: string;
  newServiceAuthorizationToken: string;
  containerConfigJson: string;
  containerPort: number | undefined;
  newTagDrafts: string[];
  newTagInputValue: string;
  addingService: boolean;
  setNewServiceName: (value: string) => void;
  setNewServiceDesc: (value: string) => void;
  setNewTransportType: (value: McpTransportType) => void;
  setNewServiceUrl: (value: string) => void;
  setNewServiceAuthorizationToken: (value: string) => void;
  setContainerConfigJson: (value: string) => void;
  setContainerPort: (value: number | undefined) => void;
  addNewTag: () => void;
  removeNewTag: (index: number) => void;
  setNewTagInputValue: (value: string) => void;
  handleAddService: () => void;
  handleSuggestContainerPort: () => void;
  containerPortCheckLoading: boolean;
  containerPortSuggesting: boolean;
  containerPortAvailable: boolean;
  t: (key: string, params?: Record<string, unknown>) => string;
}

export default function AddMcpServiceLocalSection({
  newServiceName,
  newServiceDesc,
  newTransportType,
  newServiceUrl,
  newServiceAuthorizationToken,
  containerConfigJson,
  containerPort,
  newTagDrafts,
  newTagInputValue,
  addingService,
  setNewServiceName,
  setNewServiceDesc,
  setNewTransportType,
  setNewServiceUrl,
  setNewServiceAuthorizationToken,
  setContainerConfigJson,
  setContainerPort,
  addNewTag,
  removeNewTag,
  setNewTagInputValue,
  handleAddService,
  handleSuggestContainerPort,
  containerPortCheckLoading,
  containerPortSuggesting,
  containerPortAvailable,
  t,
}: Props) {
  const [form] = Form.useForm();
  const [descriptionExpanded, setDescriptionExpanded] = useState(false);

  const isHttpUrl = (value: string): boolean => {
    try {
      const parsed = new URL(value);
      return parsed.protocol === "http:" || parsed.protocol === "https:";
    } catch {
      return false;
    }
  };

  useEffect(() => {
    form.setFieldsValue({
      newServiceName,
      newServiceDesc,
      newTransportType,
      newServiceUrl,
      newServiceAuthorizationToken,
      containerConfigJson,
      containerPort,
    });
  }, [
    containerConfigJson,
    containerPort,
    form,
    newServiceAuthorizationToken,
    newServiceDesc,
    newServiceName,
    newServiceUrl,
    newTransportType,
  ]);

  const canToggleDescription = useMemo(() => {
    const text = String(newServiceDesc || "");
    return text.length > 280 || text.split("\n").length > 8;
  }, [newServiceDesc]);

  return (
    <>
      <Form form={form} layout="vertical" requiredMark={false} className="px-6 py-5 space-y-4">
        <Form.Item
          label={t("mcpTools.addModal.name")}
          name="newServiceName"
          className="mb-0 text-sm text-slate-500"
          rules={[
            { required: true, whitespace: true, message: t("mcpTools.add.validate.nameRequired") },
            { type: "string", max: 100, message: t("mcpTools.add.validate.nameMaxLength") },
          ]}
        >
          <Input
            value={newServiceName}
            onChange={(event) => {
              setNewServiceName(event.target.value);
              form.setFieldValue("newServiceName", event.target.value);
            }}
            className="mt-2 w-full rounded-2xl"
          />
        </Form.Item>

        <Form.Item
          label={t("mcpTools.addModal.description")}
          name="newServiceDesc"
          className="mb-0 text-sm text-slate-500"
          rules={[
            { type: "string", max: 5000, message: t("mcpTools.add.validate.descriptionMaxLength") },
          ]}
        >
          <Input.TextArea
            value={newServiceDesc}
            onChange={(event) => {
              setNewServiceDesc(event.target.value);
              form.setFieldValue("newServiceDesc", event.target.value);
            }}
            autoSize={{ minRows: 1, maxRows: 20 }}
            className="mt-2 w-full rounded-2xl"
            placeholder={t("mcpTools.community.descriptionMarkdownPlaceholder")}
          />
        </Form.Item>
        <div>
          <p className="mt-2 text-[11px] text-slate-400">{t("mcpTools.community.descriptionMarkdownHint")}</p>
          <div className="mt-2 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                {t("mcpTools.community.descriptionPreview")}
              </p>
              {canToggleDescription ? (
                <Button type="link" className="px-0" onClick={() => setDescriptionExpanded((prev) => !prev)}>
                  {descriptionExpanded ? t("mcpTools.detail.descriptionCollapse") : t("mcpTools.detail.descriptionExpand")}
                </Button>
              ) : null}
            </div>
            <div className={descriptionExpanded ? "" : "max-h-40 overflow-hidden"}>
              <MarkdownRenderer
                content={newServiceDesc.trim() || "-"}
                className="text-sm text-slate-700"
                enableMultimodal={false}
                showDiagramToggle={false}
              />
            </div>
          </div>
        </div>

        <Form.Item
          label={t("mcpTools.addModal.serverType")}
          name="newTransportType"
          className="mb-0 text-sm text-slate-500"
          rules={[{ required: true, message: t("mcpTools.add.validate.transportTypeRequired") }]}
        >
          <Select
            value={newTransportType}
            onChange={(value) => {
              setNewTransportType(value);
              form.setFieldValue("newTransportType", value);
            }}
            className="mt-2 w-full"
            options={[
              { label: t("mcpTools.serverType.http"), value: MCP_TRANSPORT_TYPE.HTTP },
              { label: t("mcpTools.serverType.sse"), value: MCP_TRANSPORT_TYPE.SSE },
              { label: t("mcpTools.serverType.stdio"), value: MCP_TRANSPORT_TYPE.STDIO },
            ]}
          />
        </Form.Item>

        {newTransportType === MCP_TRANSPORT_TYPE.HTTP || newTransportType === MCP_TRANSPORT_TYPE.SSE ? (
          <div className="space-y-4">
            <Form.Item
              label={t("mcpTools.addModal.serverUrl")}
              name="newServiceUrl"
              className="mb-0 text-sm text-slate-500"
              rules={[
                {
                  validator: async (_rule, value) => {
                    const text = String(value || "").trim();
                    if (!text) {
                      throw new Error(t("mcpTools.add.validate.httpUrlRequired"));
                    }
                    if (text.length > 500) {
                      throw new Error(t("mcpTools.add.validate.httpUrlMaxLength"));
                    }
                    if (!isHttpUrl(text)) {
                      throw new Error(t("mcpTools.add.validate.httpUrlFormat"));
                    }
                  },
                },
              ]}
            >
              <Input
                value={newServiceUrl}
                onChange={(event) => {
                  setNewServiceUrl(event.target.value);
                  form.setFieldValue("newServiceUrl", event.target.value);
                }}
                className="mt-2 w-full rounded-2xl"
                placeholder={t("mcpTools.addModal.serverUrl")}
              />
            </Form.Item>
            <Form.Item
              label={t("mcpTools.addModal.bearerTokenOptional")}
              name="newServiceAuthorizationToken"
              className="mb-0 text-sm text-slate-500"
              rules={[{ type: "string", max: 500, message: t("mcpTools.add.validate.authorizationTokenMaxLength") }]}
            >
              <Input
                value={newServiceAuthorizationToken}
                onChange={(event) => {
                  setNewServiceAuthorizationToken(event.target.value);
                  form.setFieldValue("newServiceAuthorizationToken", event.target.value);
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
                    if (!text) {
                      throw new Error(t("mcpTools.add.validate.containerConfigRequired"));
                    }
                    try {
                      JSON.parse(text);
                    } catch {
                      throw new Error(t("mcpTools.add.error.containerJsonInvalid"));
                    }
                  },
                },
              ]}
            >
              <Input.TextArea
                value={containerConfigJson}
                onChange={(event) => {
                  setContainerConfigJson(event.target.value);
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
                      throw new Error(t("mcpTools.add.validate.containerRequired"));
                    }
                    const port = Number(value);
                    if (!Number.isInteger(port) || port < 1 || port > 65535) {
                      throw new Error(t("mcpTools.add.validate.containerPortRange"));
                    }
                  },
                },
              ]}
            >
              <div>
                <ContainerPortField
                  containerPort={containerPort}
                  containerPortCheckLoading={containerPortCheckLoading}
                  containerPortSuggesting={containerPortSuggesting}
                  containerPortAvailable={containerPortAvailable}
                  setContainerPort={(value) => {
                    setContainerPort(value);
                    form.setFieldValue("containerPort", value);
                  }}
                  handleSuggestContainerPort={handleSuggestContainerPort}
                  t={t}
                />
              </div>
            </Form.Item>
          </div>
        )}

        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{t("mcpTools.addModal.tags")}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {newTagDrafts.map((tag, index) => (
              <span key={`${tag}-${index}`} className="relative inline-flex">
                <Tag className="rounded-full px-3 py-1 m-0 leading-none">{tag}</Tag>
                <button
                  type="button"
                  onClick={() => removeNewTag(index)}
                  className="absolute top-0 right-0 -translate-y-1/2 translate-x-1/2 flex h-4 w-4 items-center justify-center rounded-full bg-slate-200 text-[10px] text-slate-500 transition hover:bg-slate-300 hover:text-slate-700"
                  aria-label={t("mcpTools.addModal.removeTagAria", { tag })}
                >
                  x
                </button>
              </span>
            ))}
            <Input
              size="small"
              value={newTagInputValue}
              onChange={(event) => setNewTagInputValue(event.target.value)}
              onPressEnter={addNewTag}
              onBlur={addNewTag}
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
          onClick={async () => {
            try {
              await form.validateFields();
              handleAddService();
            } catch {
              return;
            }
          }}
          loading={addingService}
        >
          {t("mcpTools.addModal.saveAndAdd")}
        </Button>
      </div>
    </>
  );
}

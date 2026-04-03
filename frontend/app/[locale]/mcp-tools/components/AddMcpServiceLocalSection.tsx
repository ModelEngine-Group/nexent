import { useMemo, useState } from "react";
import { Button, Input, InputNumber, Select, Tag } from "antd";
import { MCP_TRANSPORT_TYPE } from "@/const/mcpTools";
import type { McpTransportType } from "@/types/mcpTools";
import { MarkdownRenderer } from "@/components/ui/markdownRenderer";

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
  t,
}: Props) {
  const [descriptionExpanded, setDescriptionExpanded] = useState(false);

  const canToggleDescription = useMemo(() => {
    const text = String(newServiceDesc || "");
    return text.length > 280 || text.split("\n").length > 8;
  }, [newServiceDesc]);

  return (
    <>
      <div className="px-6 py-5 space-y-4">
        <label className="block text-sm text-slate-500">
          {t("mcpTools.addModal.name")}
          <Input
            value={newServiceName}
            onChange={(event) => setNewServiceName(event.target.value)}
            className="mt-2 w-full rounded-2xl"
          />
        </label>

        <label className="block text-sm text-slate-500">
          {t("mcpTools.addModal.description")}
          <Input.TextArea
            value={newServiceDesc}
            onChange={(event) => setNewServiceDesc(event.target.value)}
            autoSize={{ minRows: 1, maxRows: 20 }}
            className="mt-2 w-full rounded-2xl"
            placeholder={t("mcpTools.community.descriptionMarkdownPlaceholder")}
          />
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
        </label>

        <label className="block text-sm text-slate-500">
          {t("mcpTools.addModal.serverType")}
          <Select
            value={newTransportType}
            onChange={(value) => setNewTransportType(value)}
            className="mt-2 w-full"
            options={[
              { label: t("mcpTools.serverType.http"), value: MCP_TRANSPORT_TYPE.HTTP },
              { label: t("mcpTools.serverType.sse"), value: MCP_TRANSPORT_TYPE.SSE },
              { label: t("mcpTools.serverType.stdio"), value: MCP_TRANSPORT_TYPE.STDIO },
            ]}
          />
        </label>

        {newTransportType === MCP_TRANSPORT_TYPE.HTTP || newTransportType === MCP_TRANSPORT_TYPE.SSE ? (
          <div className="space-y-4">
            <label className="block text-sm text-slate-500">
              {t("mcpTools.addModal.serverUrl")}
              <Input
                value={newServiceUrl}
                onChange={(event) => setNewServiceUrl(event.target.value)}
                className="mt-2 w-full rounded-2xl"
                placeholder={t("mcpTools.addModal.serverUrl")}
              />
            </label>
            <label className="block text-sm text-slate-500">
              {t("mcpTools.addModal.bearerTokenOptional")}
              <Input
                value={newServiceAuthorizationToken}
                onChange={(event) => setNewServiceAuthorizationToken(event.target.value)}
                className="mt-2 w-full rounded-2xl"
                placeholder={t("mcpTools.addModal.bearerTokenPlaceholder")}
              />
            </label>
          </div>
        ) : (
          <div className="space-y-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <label className="block text-sm text-slate-500">
              {t("mcpTools.addModal.containerConfig")}
              <Input.TextArea
                value={containerConfigJson}
                onChange={(event) => setContainerConfigJson(event.target.value)}
                rows={5}
                placeholder={t("mcpTools.addModal.containerConfigPlaceholder")}
                className="mt-2"
              />
            </label>

            <label className="block text-sm text-slate-500">
              {t("mcpTools.addModal.containerPort")}
              <InputNumber
                value={containerPort}
                onChange={(value) => setContainerPort(value === null ? undefined : value)}
                min={1}
                max={65535}
                controls={false}
                className="mt-2 w-full"
                placeholder={t("mcpTools.addModal.containerPortPlaceholder")}
              />
            </label>
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
      </div>

      <div className="flex items-center justify-end gap-3 border-t border-slate-100 px-6 py-4">
        <Button type="primary" className="rounded-full" onClick={handleAddService} loading={addingService}>
          {t("mcpTools.addModal.saveAndAdd")}
        </Button>
      </div>
    </>
  );
}

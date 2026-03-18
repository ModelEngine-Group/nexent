import { Button, Input, InputNumber, Select, Tag, Upload } from "antd";
import { MCP_SERVER_TYPE } from "@/const/mcpTools";
import type { AddMcpLocalActions, AddMcpLocalState } from "@/types/mcpTools";

interface Props {
  state: AddMcpLocalState;
  actions: AddMcpLocalActions;
  t: (key: string, params?: Record<string, unknown>) => string;
}

export default function AddMcpServiceLocalSection({ state, actions, t }: Props) {
  return (
    <>
      <div className="px-6 py-5 space-y-4">
        <label className="block text-sm text-slate-500">
          {t("mcpTools.addModal.name")}
          <Input
            value={state.newServiceName}
            onChange={(event) => actions.onNewServiceNameChange(event.target.value)}
            className="mt-2 w-full rounded-2xl"
          />
        </label>

        <label className="block text-sm text-slate-500">
          {t("mcpTools.addModal.description")}
          <Input
            value={state.newServiceDesc}
            onChange={(event) => actions.onNewServiceDescChange(event.target.value)}
            className="mt-2 w-full rounded-2xl"
          />
        </label>

        <label className="block text-sm text-slate-500">
          {t("mcpTools.addModal.serverType")}
          <Select
            value={state.newServerType}
            onChange={(value) => actions.onNewServerTypeChange(value)}
            className="mt-2 w-full"
            options={[
              { label: t("mcpTools.serverType.http"), value: MCP_SERVER_TYPE.HTTP },
              { label: t("mcpTools.serverType.sse"), value: MCP_SERVER_TYPE.SSE },
              { label: t("mcpTools.serverType.container"), value: MCP_SERVER_TYPE.CONTAINER },
            ]}
          />
        </label>

        {state.newServerType === MCP_SERVER_TYPE.HTTP || state.newServerType === MCP_SERVER_TYPE.SSE ? (
          <div className="space-y-4">
            <label className="block text-sm text-slate-500">
              {t("mcpTools.addModal.serverUrl")}
              <Input
                value={state.newServiceUrl}
                onChange={(event) => actions.onNewServiceUrlChange(event.target.value)}
                className="mt-2 w-full rounded-2xl"
                placeholder={t("mcpTools.addModal.serverUrl")}
              />
            </label>
            <label className="block text-sm text-slate-500">
              {t("mcpTools.addModal.bearerTokenOptional")}
              <Input
                value={state.newServiceAuthorizationToken}
                onChange={(event) => actions.onNewServiceAuthorizationTokenChange(event.target.value)}
                className="mt-2 w-full rounded-2xl"
                placeholder={t("mcpTools.addModal.bearerTokenPlaceholder")}
              />
            </label>
          </div>
        ) : (
          <div className="space-y-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div>
              <p className="text-sm text-slate-700">{t("mcpTools.addModal.uploadImageTitle")}</p>
              <p className="mt-1 text-xs text-slate-500">{t("mcpTools.addModal.uploadImageDesc")}</p>
              <div className="mt-2">
                <Upload
                  fileList={state.containerUploadFileList}
                  onChange={({ fileList }) => actions.onContainerUploadFileListChange(fileList)}
                  beforeUpload={() => false}
                  accept=".tar"
                  maxCount={1}
                >
                  <Button className="rounded-full" type="default">{t("mcpTools.addModal.selectImage")}</Button>
                </Upload>
              </div>
            </div>

            <label className="block text-sm text-slate-500">
              {t("mcpTools.addModal.containerConfig")}
              <Input.TextArea
                value={state.containerConfigJson}
                onChange={(event) => actions.onContainerConfigJsonChange(event.target.value)}
                rows={5}
                placeholder={t("mcpTools.addModal.containerConfigPlaceholder")}
                className="mt-2"
              />
            </label>

            <div className="grid grid-cols-2 gap-4">
              <label className="block text-sm text-slate-500">
                {t("mcpTools.addModal.containerPort")}
                <InputNumber
                  value={state.containerPort}
                  onChange={(value) => actions.onContainerPortChange(value === null ? undefined : value)}
                  min={1}
                  max={65535}
                  controls={false}
                  className="mt-2 w-full"
                  placeholder={t("mcpTools.addModal.containerPortPlaceholder")}
                />
              </label>
              <label className="block text-sm text-slate-500">
                {t("mcpTools.addModal.containerServiceName")}
                <Input
                  value={state.containerServiceName}
                  onChange={(event) => actions.onContainerServiceNameChange(event.target.value)}
                  className="mt-2 w-full rounded-2xl"
                  placeholder={t("mcpTools.addModal.containerServiceNamePlaceholder")}
                />
              </label>
            </div>
          </div>
        )}

        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{t("mcpTools.addModal.tags")}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {state.newTagDrafts.map((tag, index) => (
              <span key={`${tag}-${index}`} className="relative inline-flex">
                <Tag className="rounded-full px-3 py-1 m-0 leading-none">{tag}</Tag>
                <button
                  type="button"
                  onClick={() => actions.onRemoveNewTag(index)}
                  className="absolute top-0 right-0 -translate-y-1/2 translate-x-1/2 flex h-4 w-4 items-center justify-center rounded-full bg-slate-200 text-[10px] text-slate-500 transition hover:bg-slate-300 hover:text-slate-700"
                  aria-label={t("mcpTools.addModal.removeTagAria", { tag })}
                >
                  x
                </button>
              </span>
            ))}
            <Input
              size="small"
              value={state.newTagInputValue}
              onChange={(event) => actions.onNewTagInputChange(event.target.value)}
              onPressEnter={actions.onAddNewTag}
              onBlur={actions.onAddNewTag}
              placeholder={t("mcpTools.addModal.tagInputPlaceholder")}
              className="w-40 rounded-full"
            />
          </div>
        </div>
      </div>

      <div className="flex items-center justify-end gap-3 border-t border-slate-100 px-6 py-4">
        <Button type="primary" className="rounded-full" onClick={actions.onSaveAndAdd} loading={state.addingService}>
          {t("mcpTools.addModal.saveAndAdd")}
        </Button>
      </div>
    </>
  );
}

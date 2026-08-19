"use client";

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Button,
  InputNumber,
  Modal,
  Select,
  Spin,
  Switch,
  Tag,
  Tooltip,
} from "antd";
import { Settings, Plus, Info } from "lucide-react";

import KnowledgeBaseSelectorModal from "@/components/tool-config/KnowledgeBaseSelectorModal";
import { useKnowledgeBasesForToolConfig } from "@/hooks/useKnowledgeBaseSelector";
import { useToolList } from "@/hooks/agent/useToolList";
import { useAgentStore } from "@/stores/agentStore";
import { useAgentReadOnly } from "@/hooks/agent/useAgentReadOnly";
import type { Tool, ToolParam } from "@/types/agentConfig";
import type { KnowledgeBase } from "@/types/knowledgeBase";

const KNOWLEDGE_BASE_SEARCH = "knowledge_base_search";
const INDEX_NAMES_PARAM = "index_names";

function parseSelectedIds(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String).filter(Boolean);
  if (typeof value !== "string" || !value.trim()) return [];

  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed.map(String).filter(Boolean) : [];
  } catch {
    return value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }
}

function getParamValue(tool: Tool | undefined, name: string): unknown {
  return tool?.initParams?.find((param) => param.name === name)?.value;
}

function updateParam(tool: Tool, name: string, value: unknown): Tool {
  const params = [...(tool.initParams || [])];
  const index = params.findIndex((param) => param.name === name);
  if (index < 0) {
    params.push({
      name,
      type: "array",
      required: false,
      value,
      description: "Knowledge base index names used for retrieval",
    });
  } else {
    params[index] = { ...params[index], value };
  }
  return { ...tool, initParams: params };
}

function getLocalizedParamDescription(
  param: ToolParam,
  language: string
): string | undefined {
  if (language.toLowerCase().startsWith("zh")) {
    return param.description_zh || param.description;
  }
  return param.description || param.description_zh;
}

function isKnowledgeBaseSearchTool(tool: Tool): boolean {
  return (
    tool.name === KNOWLEDGE_BASE_SEARCH ||
    tool.origin_name === KNOWLEDGE_BASE_SEARCH
  );
}

function prepareKnowledgeBaseSearchTool(tool: Tool): Tool {
  return {
    ...tool,
    name: tool.name || KNOWLEDGE_BASE_SEARCH,
    origin_name: tool.origin_name || KNOWLEDGE_BASE_SEARCH,
    initParams: tool.initParams || [],
  };
}

function renderParamInput(
  t: (key: string) => string,
  param: ToolParam,
  value: unknown,
  onChange: (value: unknown) => void
) {
  if (param.type === "boolean") {
    return <Switch checked={Boolean(value)} onChange={onChange} />;
  }

  if (param.type === "number") {
    return (
      <InputNumber
        className="w-full"
        value={typeof value === "number" ? value : undefined}
        onChange={onChange}
        placeholder={
          param.default || t("agent.knowledge.inputNumberPlaceholder")
        }
      />
    );
  }

  if (param.name === "search_mode") {
    return (
      <Select
        className="w-full"
        value={typeof value === "string" ? value : undefined}
        onChange={onChange}
        options={[
          { label: t("agent.knowledge.searchMode.hybrid"), value: "hybrid" },
          {
            label: t("agent.knowledge.searchMode.accurate"),
            value: "accurate",
          },
          {
            label: t("agent.knowledge.searchMode.semantic"),
            value: "semantic",
          },
        ]}
      />
    );
  }

  return (
    <input
      className="h-8 w-full rounded-md border border-gray-200 bg-white px-2 text-sm outline-none focus:border-primary"
      value={typeof value === "string" ? value : ""}
      onChange={(event) => onChange(event.target.value)}
      placeholder={param.default || t("agent.knowledge.paramPlaceholder")}
    />
  );
}

interface KnowledgeBaseConfigState {
  selectedIds: string[];
  selectedKnowledgeBases: KnowledgeBase[];
  knowledgeBases: KnowledgeBase[];
  configurableParams: ToolParam[];
  knowledgeSearchTool: Tool;
  isReadOnly: boolean;
  isLoading: boolean;
  isError: boolean;
  refetch: () => Promise<unknown>;
  onKnowledgeBaseConfirm: (knowledgeBaseList: KnowledgeBase[]) => void;
  onKnowledgeBaseRemove: (knowledgeBase: KnowledgeBase) => void;
  onParamChange: (param: ToolParam, value: unknown) => void;
}

function useKnowledgeBaseConfigState(): KnowledgeBaseConfigState | null {
  const selectedTools = useAgentStore(
    (state) => state.editedAgent?.tools ?? []
  );
  const updateTools = useAgentStore((state) => state.updateTools);
  const isReadOnly = useAgentReadOnly();

  const { availableTools, isLoading: isToolsLoading } = useToolList({
    enabled: true,
  });
  const availableKnowledgeSearchTool = useMemo(
    () => availableTools.find((tool) => isKnowledgeBaseSearchTool(tool)),
    [availableTools]
  );
  const selectedKnowledgeSearchTool = useMemo(
    () => selectedTools.find((tool) => isKnowledgeBaseSearchTool(tool)),
    [selectedTools]
  );
  const knowledgeSearchTool =
    selectedKnowledgeSearchTool || availableKnowledgeSearchTool;
  const configuredKnowledgeSearchTool = knowledgeSearchTool
    ? prepareKnowledgeBaseSearchTool(knowledgeSearchTool)
    : undefined;
  const {
    data: knowledgeBases = [],
    isLoading,
    isError,
    refetch,
  } = useKnowledgeBasesForToolConfig(KNOWLEDGE_BASE_SEARCH);

  const selectedIds = parseSelectedIds(
    getParamValue(configuredKnowledgeSearchTool, INDEX_NAMES_PARAM)
  );
  const configurableParams = (
    configuredKnowledgeSearchTool?.initParams || []
  ).filter((param) => param.name !== INDEX_NAMES_PARAM);
  const selectedKnowledgeBases = knowledgeBases.filter((knowledgeBase) =>
    selectedIds.includes(String(knowledgeBase.index_name || knowledgeBase.id))
  );

  const updateKnowledgeSearchTool = (updatedTool: Tool) => {
    const existingToolIndex = selectedTools.findIndex(
      (tool) => String(tool.id) === String(updatedTool.id)
    );
    if (existingToolIndex < 0) {
      updateTools([...selectedTools, updatedTool]);
      return;
    }
    const nextTools = [...selectedTools];
    nextTools[existingToolIndex] = updatedTool;
    updateTools(nextTools);
  };

  const onParamChange = (param: ToolParam, value: unknown) => {
    if (!selectedKnowledgeSearchTool) return;
    updateKnowledgeSearchTool(
      updateParam(selectedKnowledgeSearchTool, param.name, value)
    );
  };

  const onKnowledgeBaseConfirm = (knowledgeBaseList: KnowledgeBase[]) => {
    if (!configuredKnowledgeSearchTool) return;
    if (!selectedKnowledgeSearchTool && knowledgeBaseList.length === 0) return;
    const indexNames = knowledgeBaseList.map((knowledgeBase) =>
      String(knowledgeBase.index_name || knowledgeBase.id)
    );
    const displayNames = knowledgeBaseList.map(
      (knowledgeBase) =>
        knowledgeBase.display_name ||
        knowledgeBase.name ||
        String(knowledgeBase.id)
    );
    const updatedTool = updateParam(
      configuredKnowledgeSearchTool,
      INDEX_NAMES_PARAM,
      indexNames
    );
    updateKnowledgeSearchTool({ ...updatedTool, display_names: displayNames });
  };

  const onKnowledgeBaseRemove = (knowledgeBase: KnowledgeBase) => {
    const knowledgeBaseKey = String(
      knowledgeBase.index_name || knowledgeBase.id
    );
    onKnowledgeBaseConfirm(
      selectedKnowledgeBases.filter(
        (selectedKnowledgeBase) =>
          String(
            selectedKnowledgeBase.index_name || selectedKnowledgeBase.id
          ) !== knowledgeBaseKey
      )
    );
  };

  if (isToolsLoading || !configuredKnowledgeSearchTool) return null;

  return {
    selectedIds,
    selectedKnowledgeBases,
    knowledgeBases,
    configurableParams,
    knowledgeSearchTool: configuredKnowledgeSearchTool,
    isReadOnly,
    isLoading,
    isError,
    refetch,
    onKnowledgeBaseConfirm,
    onKnowledgeBaseRemove,
    onParamChange,
  };
}

export function KnowledgeBaseConfigActions() {
  const { t, i18n } = useTranslation("common");
  const state = useKnowledgeBaseConfigState();
  const [selectorOpen, setSelectorOpen] = useState(false);
  const [configOpen, setConfigOpen] = useState(false);

  if (!state) return null;

  return (
    <>
      <Button
        size="middle"
        icon={<Settings size={14} />}
        disabled={state.isReadOnly}
        onClick={() => setConfigOpen(true)}
      >
        {t("agent.knowledge.button.configure")}
      </Button>
      <Button
        size="middle"
        icon={<Plus size={14} />}
        disabled={state.isReadOnly}
        onClick={() => setSelectorOpen(true)}
      >
        {t("agent.knowledge.button.select")}
      </Button>

      <KnowledgeBaseSelectorModal
        isOpen={selectorOpen}
        onClose={() => setSelectorOpen(false)}
        onConfirm={(knowledgeBaseList) => {
          state.onKnowledgeBaseConfirm(knowledgeBaseList);
          setSelectorOpen(false);
        }}
        selectedIds={state.selectedIds}
        toolType={KNOWLEDGE_BASE_SEARCH}
        knowledgeBases={state.knowledgeBases}
        isLoading={state.isLoading}
        showCheckbox
        title={t("agent.knowledge.selectModal.title")}
        onSync={async () => {
          await state.refetch();
        }}
      />
      <Modal
        open={configOpen}
        title={t("agent.knowledge.configModal.title")}
        onCancel={() => setConfigOpen(false)}
        footer={null}
      >
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {state.configurableParams.map((param) => {
            const description = getLocalizedParamDescription(
              param,
              i18n.language
            );
            return (
              <label key={param.name} className="space-y-1.5">
                <span className="flex items-center gap-1 text-xs font-medium text-gray-600">
                  {param.name}
                  {description && (
                    <Tooltip title={description}>
                      <Info
                        size={13}
                        className="cursor-help text-gray-400"
                        aria-label={description}
                      />
                    </Tooltip>
                  )}
                </span>
                {renderParamInput(
                  t,
                  param,
                  getParamValue(state.knowledgeSearchTool, param.name),
                  (value) => state.onParamChange(param, value)
                )}
              </label>
            );
          })}
        </div>
      </Modal>
    </>
  );
}

export default function KnowledgeBaseConfig() {
  const { t } = useTranslation("common");
  const state = useKnowledgeBaseConfigState();

  if (!state) {
    return <Spin size="small" />;
  }

  return (
    <div className="space-y-3">
      {state.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Spin size="small" /> {t("agent.knowledge.loading")}
        </div>
      ) : state.isError ? (
        <div className="flex items-center justify-between rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">
          <span>{t("agent.knowledge.loadFailed")}</span>
          <Button size="small" onClick={() => state.refetch()}>
            {t("common.retry")}
          </Button>
        </div>
      ) : state.selectedKnowledgeBases.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {state.selectedKnowledgeBases.map((knowledgeBase) => (
            <Tag
              key={knowledgeBase.id}
              closable={!state.isReadOnly}
              onClose={
                !state.isReadOnly
                  ? () => state.onKnowledgeBaseRemove(knowledgeBase)
                  : undefined
              }
              className="!inline-flex !items-center !gap-1 !whitespace-nowrap !px-2.5 !py-1 !text-sm !text-foreground !bg-primary/5 !border !border-primary/20 !rounded-full transition-colors hover:!border-primary/40 hover:!shadow-sm"
            >
              <span className="max-w-full truncate">
                {knowledgeBase.display_name || knowledgeBase.name}
              </span>
            </Tag>
          ))}
        </div>
      ) : (
        <div className="flex min-h-20 items-center justify-center gap-4 rounded-md border border-dashed border-gray-300 bg-white px-4 py-3">
          <div className="flex items-center gap-3">
            <div>
              <p className="text-sm font-medium text-gray-700"></p>
              <p className="mt-0.5 text-xs text-gray-400">
                {t("agent.knowledge.emptyHint")}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

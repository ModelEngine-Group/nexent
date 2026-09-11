"use client";

import { useMemo, useState } from "react";
import { KnowledgeRetrievalParamsForm } from "@/components/tool-config/KnowledgeRetrievalParamsForm";
import { useTranslation } from "react-i18next";
import { Button, Modal, Spin, Tag } from "antd";
import { Settings, Plus } from "lucide-react";

import KnowledgeBaseSelectorModal from "@/components/tool-config/KnowledgeBaseSelectorModal";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { useKnowledgeBasesForToolConfig } from "@/hooks/useKnowledgeBaseSelector";
import { useToolList } from "@/hooks/agent/useToolList";
import { useAgentStore } from "@/stores/agentStore";
import { useAgentReadOnly } from "@/hooks/agent/useAgentReadOnly";
import {
  AIDP_NON_PERSISTED_PARAM_NAMES,
  getSemanticToolName,
  isManagedKnowledgeTool,
  type ManagedKnowledgeToolName,
} from "@/lib/managedKnowledgeTools";
import type { Tool, ToolParam } from "@/types/agentConfig";
import type { KnowledgeBase } from "@/types/knowledgeBase";

type KnowledgeSelectorType = "knowledge_base_search" | "aidp_search";

export interface KnowledgeToolProfile {
  toolName: ManagedKnowledgeToolName;
  selectorType: KnowledgeSelectorType;
  selectionParam: "index_names" | "kds_list";
  maxSelect?: number;
}

const LOCAL_KNOWLEDGE_PROFILE: KnowledgeToolProfile = {
  toolName: "knowledge_base_search",
  selectorType: "knowledge_base_search",
  selectionParam: "index_names",
};

const AIDP_KNOWLEDGE_PROFILE: KnowledgeToolProfile = {
  toolName: "aidp_search",
  selectorType: "aidp_search",
  selectionParam: "kds_list",
  maxSelect: 10,
};

const normalizeIds = (values: unknown[]): string[] =>
  Array.from(
    new Set(values.map((value) => String(value).trim()).filter(Boolean))
  );

const parseStringListValue = (value: unknown): string[] => {
  if (Array.isArray(value)) return normalizeIds(value);
  if (typeof value !== "string" || !value.trim()) return [];

  try {
    const parsed = JSON.parse(value);
    if (Array.isArray(parsed)) return normalizeIds(parsed);
    if (typeof parsed === "string") {
      return normalizeIds(parsed.split(","));
    }
  } catch {
    return normalizeIds(value.split(","));
  }
  return [];
};

export function parseSelection(
  tool: Tool | undefined,
  profile: KnowledgeToolProfile
): string[] {
  const value = tool?.initParams?.find(
    (param) => param.name === profile.selectionParam
  )?.value;
  return parseStringListValue(value);
}

export function serializeSelection(
  ids: string[],
  profile: KnowledgeToolProfile
): string[] | string {
  const normalizedIds = normalizeIds(ids);
  return profile.selectionParam === "kds_list"
    ? JSON.stringify(normalizedIds)
    : normalizedIds;
}

function getParamValue(tool: Tool | undefined, name: string): unknown {
  return tool?.initParams?.find((param) => param.name === name)?.value;
}

function updateParam(
  tool: Tool,
  name: string,
  value: unknown,
  type: ToolParam["type"] = "string"
): Tool {
  const params = [...(tool.initParams || [])];
  const index = params.findIndex((param) => param.name === name);
  if (index < 0) {
    params.push({
      name,
      type,
      required: false,
      value,
      description: "Knowledge bases used for retrieval",
    });
  } else {
    params[index] = { ...params[index], value };
  }
  return { ...tool, initParams: params };
}

function sanitizeManagedTool(tool: Tool, profile: KnowledgeToolProfile): Tool {
  return {
    ...tool,
    name: tool.name || profile.toolName,
    origin_name: tool.origin_name || profile.toolName,
    initParams: (tool.initParams || []).filter(
      (param) =>
        profile.toolName !== "aidp_search" ||
        !AIDP_NON_PERSISTED_PARAM_NAMES.has(param.name)
    ),
  };
}

interface SelectedKnowledgeBase {
  id: string;
  displayName: string;
}

interface KnowledgeBaseConfigState {
  profile: KnowledgeToolProfile;
  selectedIds: string[];
  selectedKnowledgeBases: SelectedKnowledgeBase[];
  knowledgeBases: KnowledgeBase[];
  configurableParams: ToolParam[];
  knowledgeSearchTool: Tool;
  hasCurrentTool: boolean;
  requiresReselection: boolean;
  isReadOnly: boolean;
  isLoading: boolean;
  isError: boolean;
  refetch: () => Promise<unknown>;
  onKnowledgeBaseConfirm: (knowledgeBaseList: KnowledgeBase[]) => void;
  onKnowledgeBaseRemove: (knowledgeBaseId: string) => void;
  onParamChange: (param: ToolParam, value: unknown) => void;
}

function useKnowledgeBaseConfigState(): KnowledgeBaseConfigState | null {
  const selectedTools = useAgentStore(
    (state) => state.editedAgent?.tools ?? []
  );
  const updateTools = useAgentStore((state) => state.updateTools);
  const isReadOnly = useAgentReadOnly();
  const { aidpEnabled, isDeploymentReady } = useDeployment();
  const profile = aidpEnabled
    ? AIDP_KNOWLEDGE_PROFILE
    : LOCAL_KNOWLEDGE_PROFILE;

  const { availableTools, isLoading: isToolsLoading } = useToolList({
    enabled: isDeploymentReady,
  });
  const availableKnowledgeSearchTool = useMemo(
    () =>
      availableTools.find(
        (tool) => getSemanticToolName(tool) === profile.toolName
      ),
    [availableTools, profile.toolName]
  );
  const selectedKnowledgeSearchTool = useMemo(
    () =>
      selectedTools.find(
        (tool) => getSemanticToolName(tool) === profile.toolName
      ),
    [selectedTools, profile.toolName]
  );
  const configuredKnowledgeSearchTool =
    selectedKnowledgeSearchTool || availableKnowledgeSearchTool
      ? sanitizeManagedTool(
          (selectedKnowledgeSearchTool || availableKnowledgeSearchTool) as Tool,
          profile
        )
      : undefined;
  const {
    data: knowledgeBases = [],
    isLoading,
    isError,
    refetch,
  } = useKnowledgeBasesForToolConfig(
    isDeploymentReady ? profile.selectorType : null
  );

  const selectedIds = parseSelection(selectedKnowledgeSearchTool, profile);
  const selectedDisplayNames = selectedKnowledgeSearchTool?.display_names || [];
  const configurableParams = (
    configuredKnowledgeSearchTool?.initParams || []
  ).filter(
    (param) =>
      param.name !== profile.selectionParam &&
      !AIDP_NON_PERSISTED_PARAM_NAMES.has(param.name)
  );
  const selectedKnowledgeBases = selectedIds.map((id, index) => {
    const knowledgeBase = knowledgeBases.find((item) => {
      const itemId =
        profile.toolName === "aidp_search"
          ? String(item.id)
          : String(item.index_name || item.id);
      return itemId === id;
    });
    return {
      id,
      displayName:
        knowledgeBase?.display_name ||
        knowledgeBase?.name ||
        selectedDisplayNames[index] ||
        id,
    };
  });
  const requiresReselection =
    !selectedKnowledgeSearchTool &&
    selectedTools.some(
      (tool) =>
        isManagedKnowledgeTool(tool) &&
        getSemanticToolName(tool) !== profile.toolName
    );

  const replaceManagedKnowledgeTool = (updatedTool?: Tool) => {
    const otherTools = selectedTools.filter(
      (tool) => !isManagedKnowledgeTool(tool)
    );
    updateTools(updatedTool ? [...otherTools, updatedTool] : otherTools);
  };

  const onParamChange = (param: ToolParam, value: unknown) => {
    if (!selectedKnowledgeSearchTool || !configuredKnowledgeSearchTool) return;
    replaceManagedKnowledgeTool(
      updateParam(configuredKnowledgeSearchTool, param.name, value, param.type)
    );
  };

  const updateSelection = (ids: string[], displayNames: string[]) => {
    if (!configuredKnowledgeSearchTool) return;
    if (!selectedKnowledgeSearchTool && ids.length === 0) return;
    if (ids.length === 0) {
      replaceManagedKnowledgeTool();
      return;
    }

    const updatedTool = updateParam(
      configuredKnowledgeSearchTool,
      profile.selectionParam,
      serializeSelection(ids, profile),
      profile.selectionParam === "kds_list" ? "string" : "array"
    );
    replaceManagedKnowledgeTool({
      ...updatedTool,
      display_names: displayNames,
    });
  };

  const onKnowledgeBaseConfirm = (knowledgeBaseList: KnowledgeBase[]) => {
    const ids = knowledgeBaseList.map((knowledgeBase) =>
      profile.toolName === "aidp_search"
        ? String(knowledgeBase.id)
        : String(knowledgeBase.index_name || knowledgeBase.id)
    );
    const displayNames = knowledgeBaseList.map(
      (knowledgeBase) =>
        knowledgeBase.display_name ||
        knowledgeBase.name ||
        String(knowledgeBase.id)
    );
    updateSelection(ids, displayNames);
  };

  const onKnowledgeBaseRemove = (knowledgeBaseId: string) => {
    const nextItems = selectedKnowledgeBases.filter(
      (knowledgeBase) => knowledgeBase.id !== knowledgeBaseId
    );
    updateSelection(
      nextItems.map((knowledgeBase) => knowledgeBase.id),
      nextItems.map((knowledgeBase) => knowledgeBase.displayName)
    );
  };

  if (!isDeploymentReady || isToolsLoading || !configuredKnowledgeSearchTool) {
    return null;
  }

  return {
    profile,
    selectedIds,
    selectedKnowledgeBases,
    knowledgeBases,
    configurableParams,
    knowledgeSearchTool: configuredKnowledgeSearchTool,
    hasCurrentTool: Boolean(selectedKnowledgeSearchTool),
    requiresReselection,
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
  const { t } = useTranslation("common");
  const state = useKnowledgeBaseConfigState();
  const [selectorOpen, setSelectorOpen] = useState(false);
  const [configOpen, setConfigOpen] = useState(false);

  if (!state) return null;

  return (
    <>
      <Button
        size="middle"
        icon={<Settings size={14} />}
        disabled={state.isReadOnly || !state.hasCurrentTool}
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
        toolType={state.profile.selectorType}
        maxSelect={state.profile.maxSelect}
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
        <KnowledgeRetrievalParamsForm
          params={state.configurableParams}
          values={Object.fromEntries(
            state.configurableParams.map((param) => [
              param.name,
              getParamValue(state.knowledgeSearchTool, param.name),
            ])
          )}
          onChange={(name, value) => {
            const param = state.configurableParams.find(
              (item) => item.name === name
            );
            if (param) state.onParamChange(param, value);
          }}
        />
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
                  ? () => state.onKnowledgeBaseRemove(knowledgeBase.id)
                  : undefined
              }
              className="!inline-flex !items-center !gap-1 !whitespace-nowrap !px-2.5 !py-1 !text-sm !text-foreground !bg-primary/5 !border !border-primary/20 !rounded-full transition-colors hover:!border-primary/40 hover:!shadow-sm"
            >
              <span className="max-w-full truncate">
                {knowledgeBase.displayName}
              </span>
            </Tag>
          ))}
        </div>
      ) : (
        <div className="flex min-h-20 items-center justify-center gap-4 rounded-md border border-dashed border-gray-300 bg-white px-4 py-3">
          <p className="text-xs text-gray-400">
            {state.requiresReselection
              ? t("agent.knowledge.reselectionRequired")
              : t("agent.knowledge.emptyHint")}
          </p>
        </div>
      )}
    </div>
  );
}

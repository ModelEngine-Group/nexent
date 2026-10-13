"use client";

import { Fragment, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { KnowledgeRetrievalParamsForm } from "@/components/tool-config/KnowledgeRetrievalParamsForm";
import { useTranslation } from "react-i18next";
import { Button, Modal, Spin, Tag, Tooltip } from "antd";
import { Database, ChevronRight, Settings, Trash2, Plus } from "lucide-react";

import { AddKnowledgeDrawer } from "@/components/resource-picker/AddKnowledgeDrawer";
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
import { formatDate } from "@/lib/date";
import { ResourceAddButton } from "@/components/common/ResourceAddButton";
import type { ResourceSectionProps } from "./resource-section.types";

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
  knowledgeBase?: KnowledgeBase;
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
      knowledgeBase,
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

      <AddKnowledgeDrawer
        open={selectorOpen}
        onClose={() => setSelectorOpen(false)}
        onConfirm={(knowledgeBaseList) => {
          state.onKnowledgeBaseConfirm(knowledgeBaseList);
          setSelectorOpen(false);
        }}
        selectedIds={state.selectedIds}
        maxSelect={state.profile.maxSelect}
        isAidpSearch={state.profile.selectorType === "aidp_search"}
        knowledgeBases={state.knowledgeBases}
        isLoading={state.isLoading}
        title={t("agent.knowledge.selectModal.title")}
        onRefresh={() => {
          void state.refetch();
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

export default function KnowledgeBaseConfig({
  highFidelity = false,
  renderSection,
}: ResourceSectionProps = {}) {
  const { t } = useTranslation("common");
  const router = useRouter();
  const state = useKnowledgeBaseConfigState();
  const [selectorOpen, setSelectorOpen] = useState(false);
  const [configOpen, setConfigOpen] = useState(false);
  const isReadOnly = useAgentReadOnly();

  if (highFidelity) {
    const selectedKnowledgeBases = state?.selectedKnowledgeBases ?? [];
    const content = (
      <div className="flex flex-col gap-2">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {selectedKnowledgeBases.map((selectedKnowledgeBase) => {
            const knowledgeBase = selectedKnowledgeBase.knowledgeBase;
            const metadata = knowledgeBase
              ? [
                  knowledgeBase.createdAt
                    ? `${formatDate(knowledgeBase.createdAt)} ${t("knowledgeBase.tag.used")}`
                    : t("knowledgeBase.tag.used"),
                  knowledgeBase.documentCount !== undefined
                    ? t("agent.knowledgeBase.card.documents", {
                        count: knowledgeBase.documentCount,
                      })
                    : undefined,
                  knowledgeBase.chunkCount !== undefined
                    ? t("agent.knowledgeBase.card.chunks", {
                        count: knowledgeBase.chunkCount,
                      })
                    : undefined,
                ].filter((value): value is string => Boolean(value))
              : [];

            return (
              <div
                key={selectedKnowledgeBase.id}
                data-testid={`agent-selected-knowledge-base-${selectedKnowledgeBase.id}`}
                className="flex h-12 min-w-0 items-center rounded-[4px] border border-solid border-[#dfdfdf] bg-white px-3 py-2 shadow-[0_2px_8px_rgba(0,0,0,0.08)]"
              >
                <span
                  data-testid="agent-knowledge-base-icon"
                  aria-hidden="true"
                  className="grid size-6 shrink-0 place-items-center rounded-md bg-gradient-to-br from-[#d8caff] via-[#ad8cf4] to-[#8060dc] shadow-[0_2px_6px_rgba(128,96,220,0.24)]"
                >
                  <Database size={16} strokeWidth={2} className="text-white" />
                </span>
                <div className="ml-2 flex min-w-0 flex-1 items-center gap-2 overflow-hidden">
                  <Tooltip title={selectedKnowledgeBase.displayName}>
                    <span
                      data-testid="agent-selected-knowledge-base-name"
                      className="min-w-0 max-w-[45%] truncate text-sm leading-[22px] text-[#191919]"
                    >
                      {selectedKnowledgeBase.displayName}
                    </span>
                  </Tooltip>
                  {metadata.length > 0 ? (
                    <Tooltip title={metadata.join(" | ")}>
                      <span
                        data-testid="agent-selected-knowledge-base-metadata"
                        className="flex max-w-[46%] shrink-0 items-center gap-2 overflow-hidden whitespace-nowrap text-xs leading-[18px] text-[#808080]"
                      >
                        {metadata.map((value, index) => (
                          <Fragment
                            key={`${selectedKnowledgeBase.id}-${index}`}
                          >
                            {index > 0 && (
                              <span
                                data-testid="agent-knowledge-base-metadata-separator"
                                aria-hidden="true"
                                className="h-4 w-px shrink-0 bg-[#dfdfdf]"
                              />
                            )}
                            <span className="truncate">{value}</span>
                          </Fragment>
                        ))}
                      </span>
                    </Tooltip>
                  ) : null}
                </div>
                <Tooltip title={t("agent.knowledge.button.configure")}>
                  <Button
                    type="text"
                    size="small"
                    icon={<Settings size={14} />}
                    aria-label={`${t("agent.knowledge.button.configure")} ${selectedKnowledgeBase.displayName}`}
                    disabled={!state || isReadOnly || !state.hasCurrentTool}
                    onClick={() => setConfigOpen(true)}
                    className="!size-6 !shrink-0 !p-0 !text-[#777777]"
                  />
                </Tooltip>
                <Tooltip title={t("skillPool.remove")}>
                  <Button
                    type="text"
                    size="small"
                    icon={<Trash2 size={14} />}
                    aria-label={`${t("skillPool.remove")} ${selectedKnowledgeBase.displayName}`}
                    disabled={!state || isReadOnly}
                    onClick={() =>
                      state?.onKnowledgeBaseRemove(selectedKnowledgeBase.id)
                    }
                    className="!size-6 !shrink-0 !p-0 !text-[#777777] hover:!text-red-500"
                  />
                </Tooltip>
              </div>
            );
          })}
          <ResourceAddButton
            data-testid="agent-knowledge-base-add-entry"
            disabled={!state || isReadOnly || state.isLoading}
            onClick={() => setSelectorOpen(true)}
          >
            {t("agentConfig.layout.addKnowledgeBase")}
          </ResourceAddButton>
        </div>
        {state?.isLoading ? <Spin size="small" /> : null}
        {state?.isError ? (
          <div className="flex items-center justify-between text-xs text-red-600">
            <span>{t("agent.knowledge.loadFailed")}</span>
            <Button size="small" onClick={() => state.refetch()}>
              {t("common.retry")}
            </Button>
          </div>
        ) : null}
        {state?.requiresReselection ? (
          <p className="text-xs leading-[22px] text-[#808080]">
            {t("agent.knowledge.reselectionRequired")}
          </p>
        ) : null}
      </div>
    );
    const actions = (
      <div className="flex h-6 items-center gap-2">
        <Button
          type="link"
          disabled={isReadOnly}
          onClick={() => router.push("/knowledges")}
          className="!h-[22px] !p-0 !text-sm !font-normal !leading-[22px] !tracking-[0px] !text-[#2673e5]"
        >
          <span className="inline-flex items-center gap-1">
            {t("agentConfig.layout.newKnowledgeBase")}
            <ChevronRight size={14} />
          </span>
        </Button>
        <Button
          type="text"
          size="small"
          icon={<Settings size={14} />}
          aria-label={t("agent.knowledge.button.configure")}
          disabled={!state || isReadOnly || !state.hasCurrentTool}
          onClick={() => setConfigOpen(true)}
          className="!size-6 !p-0 !text-[#191919]"
        />
      </div>
    );
    return (
      <>
        {renderSection ? (
          renderSection(content, actions)
        ) : (
          <div className="flex flex-col gap-2">
            <div className="flex justify-end">{actions}</div>
            {content}
          </div>
        )}
        {state ? (
          <>
            <AddKnowledgeDrawer
              open={selectorOpen}
              onClose={() => setSelectorOpen(false)}
              onConfirm={(knowledgeBaseList) => {
                state.onKnowledgeBaseConfirm(knowledgeBaseList);
                setSelectorOpen(false);
              }}
              selectedIds={state.selectedIds}
              maxSelect={state.profile.maxSelect}
              isAidpSearch={state.profile.selectorType === "aidp_search"}
              knowledgeBases={state.knowledgeBases}
              isLoading={state.isLoading}
              title={t("agent.knowledge.selectModal.title")}
              onRefresh={() => {
                void state.refetch();
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
        ) : null}
      </>
    );
  }

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

"use client";

import { useTranslation } from "react-i18next";
import {
  Button,
  Col,
  Form,
  Input,
  Modal,
  Popover,
  Row,
  Select,
  Tooltip,
} from "antd";
import {
  GripVertical,
  ListOrdered,
  Maximize2,
  Settings2,
  Sparkles,
  Trash2,
} from "lucide-react";
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  rectSortingStrategy,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import Image from "next/image";

import { useAgentStore } from "@/stores/agentStore";
import { AddModelDrawer } from "@/components/resource-picker/AddModelDrawer";
import { useModelList } from "@/hooks/model/useModelList";
import { useInferenceFieldSpecs } from "@/hooks/model/useInferenceFieldSpecs";
import type { ModelOption } from "@/types/modelConfig";
import { ResourceAddButton } from "@/components/common/ResourceAddButton";
import {
  ModelAdvancedSettings,
  ModelAdvancedSettingsValue,
  advancedSettingsValueFromRecord,
  buildModelOverrideEntry,
  diffCustomParamsForSave,
  mergeCustomParamsForEditing,
} from "../../../models/components/model/ModelAdvancedSettings";
import type { ModelOverrideMap } from "../../../models/components/model/ModelOverrideModal";
import { canManageModels } from "@/lib/auth";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { useNl2AgentFlow } from "@/contexts/nl2AgentFlow";
import { useAgentReadOnly } from "@/hooks/agent/useAgentReadOnly";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import ExpandEditModal from "@/components/common/ExpandEditModal";
import {
  reorderModelIds,
  resolveModelSelection,
} from "@/lib/agent/modelPriority";
import HighFidelityTextArea from "./HighFidelityTextArea";
import HighFidelityPromptEditModal from "./HighFidelityPromptEditModal";

const { TextArea } = Input;

type PromptTab = "duty" | "constraint" | "few-shots";

type SortableModelItemProps = {
  disabled: boolean;
  displayName: string;
  isPrimary: boolean;
  modelId: number;
  primaryLabel: string;
  reorderLabel: string;
};

function SortableModelItem({
  disabled,
  displayName,
  isPrimary,
  modelId,
  primaryLabel,
  reorderLabel,
}: SortableModelItemProps) {
  const {
    attributes,
    isDragging,
    listeners,
    setNodeRef,
    transform,
    transition,
  } = useSortable({
    id: modelId,
    disabled,
  });

  return (
    <li
      ref={setNodeRef}
      className="flex items-center gap-2 rounded border border-border bg-background px-2 py-1.5"
      style={{
        opacity: isDragging ? 0.5 : 1,
        transform: CSS.Transform.toString(transform),
        transition,
      }}
    >
      <button
        type="button"
        className="flex cursor-grab touch-none text-muted-foreground disabled:cursor-default"
        aria-label={reorderLabel}
        disabled={disabled}
        {...attributes}
        {...listeners}
      >
        <GripVertical size={16} />
      </button>
      <span className="min-w-0 flex-1 truncate">{displayName}</span>
      {isPrimary && (
        <span className="text-xs text-muted-foreground">{primaryLabel}</span>
      )}
    </li>
  );
}

const MODEL_PROVIDER_LOGOS: Record<string, string> = {
  deepseek: "/deepseek.png",
  openai: "/openai.png",
  qwen: "/qwen.png",
  silicon: "/siliconflow.png",
  siliconflow: "/siliconflow.png",
  modelengine: "/modelengine.png",
};

interface SelectedModelCardProps {
  model: ModelOption;
  disabled: boolean;
  onConfigure: () => void;
  onRemove: () => void;
  reorderLabel: string;
  settingsLabel: string;
  removeLabel: string;
  textInferenceLabel: string;
  deepThinkingLabel: string;
  toolCallsLabel: string;
  contextLabel?: string;
}

function SelectedModelCard({
  model,
  disabled,
  onConfigure,
  onRemove,
  reorderLabel,
  settingsLabel,
  removeLabel,
  textInferenceLabel,
  deepThinkingLabel,
  toolCallsLabel,
  contextLabel,
}: SelectedModelCardProps) {
  const {
    attributes,
    isDragging,
    listeners,
    setNodeRef,
    transform,
    transition,
  } = useSortable({ id: model.id, disabled });
  const provider = String(
    model.modelFactory || model.source || ""
  ).toLowerCase();
  const logo = MODEL_PROVIDER_LOGOS[provider];
  const contextTokens = model.contextWindowTokens ?? model.maxInputTokens;
  const contextSize =
    contextTokens && contextTokens > 0
      ? `${Math.round(contextTokens / 1000)}k`
      : null;
  const capabilities = [
    model.type === "llm" ? textInferenceLabel : null,
    model.reasoningCapability?.status === "supported"
      ? deepThinkingLabel
      : null,
    model.supportToolCalls === true ? toolCallsLabel : null,
  ].filter((value): value is string => Boolean(value));

  return (
    <div
      ref={setNodeRef}
      data-testid={`agent-selected-model-${model.id}`}
      className={`flex h-12 min-w-0 items-center gap-2 rounded-[4px] border border-[#d9d9d9] bg-white px-2 transition-shadow ${
        isDragging ? "z-10 opacity-60 shadow-md" : ""
      }`}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
      }}
    >
      <button
        type="button"
        className="flex size-4 shrink-0 cursor-grab touch-none items-center justify-center text-[#8c8c8c] disabled:cursor-default"
        aria-label={reorderLabel}
        disabled={disabled}
        {...attributes}
        {...listeners}
      >
        <GripVertical size={14} />
      </button>
      <span className="flex size-5 shrink-0 items-center justify-center overflow-hidden">
        {logo ? (
          <Image
            src={logo}
            alt=""
            aria-hidden="true"
            width={20}
            height={20}
            className="size-5 object-contain"
          />
        ) : (
          <Sparkles size={17} className="text-[#2673e5]" aria-hidden="true" />
        )}
      </span>
      <div className="flex min-w-0 flex-1 items-center gap-1.5 overflow-hidden">
        <Tooltip title={model.displayName || model.name}>
          <span className="min-w-0 shrink truncate text-sm leading-[22px] text-[#191919]">
            {model.displayName || model.name}
          </span>
        </Tooltip>
        {contextSize ? (
          <span className="shrink-0 rounded-[2px] bg-[#f5f5f5] px-1 text-[10px] leading-4 text-[#595959]">
            {contextLabel?.replace("{{count}}", contextSize) ?? contextSize}
          </span>
        ) : null}
        {capabilities.map((capability) => (
          <span
            key={capability}
            className="shrink-0 rounded-[2px] bg-[#f5f5f5] px-1 text-[10px] leading-4 text-[#595959]"
          >
            {capability}
          </span>
        ))}
      </div>
      <Tooltip title={settingsLabel}>
        <Button
          type="text"
          size="small"
          icon={<Settings2 size={14} />}
          aria-label={settingsLabel}
          disabled={disabled}
          onClick={onConfigure}
          className="!size-6 !shrink-0 !p-0 !text-[#777777]"
        />
      </Tooltip>
      <Tooltip title={removeLabel}>
        <Button
          type="text"
          size="small"
          icon={<Trash2 size={14} />}
          aria-label={removeLabel}
          disabled={disabled}
          onClick={onRemove}
          className="!size-6 !shrink-0 !p-0 !text-[#777777] hover:!text-red-500"
        />
      </Tooltip>
    </div>
  );
}

interface HighFidelityModelGridProps {
  value?: number[];
  onChange?: (modelIds: number[]) => void;
  selectedIds: number[];
  models: ModelOption[];
  disabled: boolean;
  onAddModel: () => void;
  onSelectionChange: (modelIds: number[]) => void;
  onConfigureModel: (modelId: number) => void;
  reorderLabel: string;
  settingsLabel: string;
  removeLabel: string;
  textInferenceLabel: string;
  deepThinkingLabel: string;
  toolCallsLabel: string;
  addModelLabel: string;
  contextLabel?: string;
  sensors: ReturnType<typeof useSensors>;
}

function HighFidelityModelGrid({
  value,
  onChange,
  selectedIds,
  models,
  disabled,
  onAddModel,
  onSelectionChange,
  onConfigureModel,
  reorderLabel,
  settingsLabel,
  removeLabel,
  textInferenceLabel,
  deepThinkingLabel,
  toolCallsLabel,
  addModelLabel,
  contextLabel,
  sensors,
}: HighFidelityModelGridProps) {
  const modelIds = value ?? selectedIds;
  const selectedModels = modelIds
    .map((id) => models.find((model) => model.id === Number(id)))
    .filter((model): model is ModelOption => Boolean(model));

  const updateSelection = (nextIds: number[]) => {
    onSelectionChange(nextIds);
    onChange?.(nextIds);
  };

  const handleDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    const oldIndex = modelIds.indexOf(Number(active.id));
    const newIndex = modelIds.indexOf(Number(over.id));
    if (oldIndex < 0 || newIndex < 0) return;
    const nextIds = [...modelIds];
    const [movedId] = nextIds.splice(oldIndex, 1);
    nextIds.splice(newIndex, 0, movedId);
    updateSelection(nextIds);
  };

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={handleDragEnd}
    >
      <SortableContext items={modelIds} strategy={rectSortingStrategy}>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {selectedModels.map((model) => (
            <SelectedModelCard
              key={model.id}
              model={model}
              disabled={disabled}
              reorderLabel={reorderLabel}
              settingsLabel={settingsLabel}
              removeLabel={removeLabel}
              textInferenceLabel={textInferenceLabel}
              deepThinkingLabel={deepThinkingLabel}
              toolCallsLabel={toolCallsLabel}
              contextLabel={contextLabel}
              onConfigure={() => onConfigureModel(model.id)}
              onRemove={() =>
                updateSelection(
                  modelIds.filter((modelId) => Number(modelId) !== model.id)
                )
              }
            />
          ))}
          <ResourceAddButton
            data-testid="agent-model-add-entry"
            aria-label={addModelLabel}
            disabled={disabled}
            onClick={onAddModel}
          >
            {addModelLabel}
          </ResourceAddButton>
        </div>
      </SortableContext>
    </DndContext>
  );
}

interface AgentPromptProps {
  highFidelity?: boolean;
  onOptimizePrompt?: () => void;
}

export default function AgentPrompt({
  highFidelity = false,
  onOptimizePrompt,
}: AgentPromptProps) {
  const { t } = useTranslation("common");
  const form = Form.useFormInstance();
  const { user } = useAuthorizationContext();
  const { availableLlmModels, isSuccess: modelListLoaded } = useModelList();
  const { isSpeedMode } = useDeployment();
  const isReadOnly = useAgentReadOnly();
  const editedAgent = useAgentStore((state) => state.editedAgent!);
  const updateDraft = useAgentStore((state) => state.updateDraft);
  const flushDraft = useAgentStore((state) => state.flushDraft);
  const updateAgent = useAgentStore((state) => state.updateAgentConfig);
  const reconcileUnavailableModels = useAgentStore(
    (state) => state.reconcileUnavailableModels
  );
  const agentId = useAgentStore((state) => state.agentId);
  const defaultLlmConfig = useAgentStore((state) => state.defaultLlmConfig);
  const { configFocusRequest } = useNl2AgentFlow();

  const [expandedPrompt, setExpandedPrompt] = useState<PromptTab | null>(null);
  const [activePromptTab, setActivePromptTab] = useState<PromptTab>("duty");
  const [isModelPriorityOpen, setIsModelPriorityOpen] = useState(false);
  const [isModelSelectionOpen, setIsModelSelectionOpen] = useState(false);
  const [additionalPromptsOpen, setAdditionalPromptsOpen] = useState(false);
  const requestedPromptTab =
    configFocusRequest?.agentId === agentId &&
    configFocusRequest.target.section === "role_model"
      ? configFocusRequest.target.promptTab
      : null;

  useEffect(() => {
    setActivePromptTab("duty");
    setIsModelSelectionOpen(false);
    setAdditionalPromptsOpen(false);
  }, [agentId]);

  useEffect(() => {
    if (requestedPromptTab) {
      setActivePromptTab(requestedPromptTab);
      if (requestedPromptTab !== "duty") setAdditionalPromptsOpen(true);
    }
  }, [requestedPromptTab]);

  const handlePromptTabChange = useCallback(
    (value: string) => {
      flushDraft();
      if (value === "duty" || value === "constraint" || value === "few-shots") {
        setActivePromptTab(value);
      }
    },
    [flushDraft]
  );

  const modelOptions = useMemo(() => {
    return (availableLlmModels ?? []).map((m) => ({
      value: m.id,
      label: m.displayName ?? m.name,
      displayName: m.displayName ?? m.name,
    }));
  }, [availableLlmModels]);

  const availableModelIds = useMemo(
    () => new Set(modelOptions.map((option) => option.value)),
    [modelOptions]
  );

  const selectedModelIds = useMemo(() => {
    const configuredModelIds = (editedAgent.model_ids ?? []).map(Number);
    if (configuredModelIds.length > 0) {
      return configuredModelIds.filter((id) => availableModelIds.has(id));
    }
    const defaultModelId = defaultLlmConfig?.id
      ? Number(defaultLlmConfig.id)
      : null;
    return defaultModelId !== null && availableModelIds.has(defaultModelId)
      ? [defaultModelId]
      : [];
  }, [availableModelIds, defaultLlmConfig?.id, editedAgent.model_ids]);

  useEffect(() => {
    if (!modelListLoaded || !editedAgent.model_ids?.length) return;

    const currentModelIds = editedAgent.model_ids.map(Number);
    const nextModelIds = currentModelIds.filter((id) =>
      availableModelIds.has(id)
    );
    if (nextModelIds.length === currentModelIds.length) return;

    // Keep the Ant Design Form value in sync with the cleaned agent draft.
    // Otherwise Form.Item can re-inject an unavailable raw model ID into Select.
    form.setFieldValue("model_ids", nextModelIds);

    const modelNames = nextModelIds.map((id) => {
      const option = modelOptions.find((model) => model.value === id);
      return option?.displayName ?? "";
    });
    const primaryModel = modelOptions.find(
      (option) => option.value === nextModelIds[0]
    );
    reconcileUnavailableModels({
      model_ids: nextModelIds,
      model: primaryModel?.displayName ?? "",
      model_names: modelNames,
    });
  }, [
    availableModelIds,
    editedAgent.model_ids,
    modelListLoaded,
    modelOptions,
    form,
    reconcileUnavailableModels,
  ]);

  const { specs: inferenceSpecs } = useInferenceFieldSpecs({ enabled: true });
  const [configuringModelId, setConfiguringModelId] = useState<number | null>(
    null
  );
  const [editingOverrideValue, setEditingOverrideValue] =
    useState<ModelAdvancedSettingsValue | null>(null);
  const modelParamsOverride = (editedAgent.model_params_override ??
    {}) as ModelOverrideMap;
  const configuringModel = useMemo(
    () =>
      (availableLlmModels ?? []).find((m) => m.id === configuringModelId) ??
      null,
    [availableLlmModels, configuringModelId]
  );
  useEffect(() => {
    if (!configuringModel) {
      setEditingOverrideValue(null);
      return;
    }
    const overrideEntry =
      modelParamsOverride[String(configuringModel.id)] ?? {};
    const modelDefaultsRecord = {
      temperature: configuringModel.temperature,
      top_p: configuringModel.topP,
      extra_params: configuringModel.extraParams,
      reasoning_capability: configuringModel.reasoningCapability,
    };
    const modelType = configuringModel.type ?? "llm";
    const hasOverride = Object.keys(overrideEntry).length > 0;
    const base = advancedSettingsValueFromRecord(
      (hasOverride ? overrideEntry : modelDefaultsRecord) as any,
      inferenceSpecs,
      modelType,
      configuringModel.reasoningCapability
    );

    // Reasoning is an agent-owned snapshot. For an existing partial override,
    // fill only missing reasoning fields from the model so older agents and
    // newly selected models start with the same value as the model page.
    if (hasOverride) {
      const modelReasoning = advancedSettingsValueFromRecord(
        modelDefaultsRecord as any,
        inferenceSpecs,
        modelType,
        configuringModel.reasoningCapability
      );
      if (
        base.enable_thinking === undefined &&
        modelReasoning.enable_thinking !== undefined
      ) {
        base.enable_thinking = modelReasoning.enable_thinking;
      }
      if (
        base.reasoning_effort === undefined &&
        modelReasoning.reasoning_effort !== undefined
      ) {
        base.reasoning_effort = modelReasoning.reasoning_effort;
      }
      if (
        base.reasoning_budget_tokens === undefined &&
        modelReasoning.reasoning_budget_tokens !== undefined
      ) {
        base.reasoning_budget_tokens = modelReasoning.reasoning_budget_tokens;
      }
    }

    // Custom params are the exception: model-level customs render as plain
    // editable rows (merged display). Deletion persists as a null marker in
    // the override entry, so deleted rows do NOT reappear on reopen.
    base.__custom__ = mergeCustomParamsForEditing(
      (overrideEntry as any).extra_params?.__custom__,
      (configuringModel as any).extraParams?.__custom__
    );
    setEditingOverrideValue(base);
    // Do not reinitialize while the user edits the override entry; the model
    // and field-spec changes are the transitions that require rehydration.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [configuringModel, configuringModelId, inferenceSpecs]);

  const handleModelParamsOverrideChange = (
    modelId: number,
    next: ModelAdvancedSettingsValue
  ) => {
    const entry = buildModelOverrideEntry(
      next,
      availableLlmModels.find((model) => model.id === modelId)
        ?.reasoningCapability
    );
    const updated: ModelOverrideMap = { ...modelParamsOverride };
    if (Object.keys(entry).length === 0) {
      delete updated[String(modelId)];
    } else {
      updated[String(modelId)] = entry;
    }
    updateAgent({
      model_params_override: Object.keys(updated).length > 0 ? updated : null,
    });
  };

  const handleClearModelParamsOverride = (modelId: number) => {
    const updated: ModelOverrideMap = { ...modelParamsOverride };
    delete updated[String(modelId)];
    updateAgent({
      model_params_override: Object.keys(updated).length > 0 ? updated : null,
    });
  };

  const canManage = canManageModels(user?.role ?? "");
  const isModelSelectionDisabled = isReadOnly || (!canManage && !isSpeedMode);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );
  const selectedModels = selectedModelIds.map((id) =>
    modelOptions.find((option) => option.value === id)
  );

  useEffect(() => {
    if (selectedModels.length < 2) setIsModelPriorityOpen(false);
  }, [selectedModels.length]);

  const updateModelSelection = useCallback(
    (modelIds: number[]) => {
      form.setFieldValue("model_ids", modelIds);
      updateAgent(resolveModelSelection(modelIds, modelOptions));
    },
    [form, modelOptions, updateAgent]
  );

  const handleModelPriorityChange = useCallback(
    ({ active, over }: DragEndEvent) => {
      if (!over) return;

      const modelIds = reorderModelIds(
        selectedModelIds,
        Number(active.id),
        Number(over.id)
      );
      updateModelSelection(modelIds);
    },
    [selectedModelIds, updateModelSelection]
  );

  const expandedPromptConfig = {
    duty: {
      title: t("agent.field.dutyPrompt"),
      content: editedAgent.duty_prompt ?? "",
      save: (content: string) => updateDraft({ duty_prompt: content }),
    },
    constraint: {
      title: t("agent.field.constraintPrompt"),
      content: editedAgent.constraint_prompt ?? "",
      save: (content: string) => updateDraft({ constraint_prompt: content }),
    },
    "few-shots": {
      title: t("agent.field.fewShotsPrompt"),
      content: editedAgent.few_shots_prompt ?? "",
      save: (content: string) => updateDraft({ few_shots_prompt: content }),
    },
  };

  const renderExpandButton = (prompt: PromptTab) => (
    <Tooltip title={t("systemPrompt.button.expand")}>
      <Button
        type="text"
        size="small"
        icon={<Maximize2 size={15} />}
        aria-label={t("systemPrompt.button.expand")}
        disabled={isReadOnly}
        onClick={() => setExpandedPrompt(prompt)}
      />
    </Tooltip>
  );

  const modelPriorityContent = (
    <div className="w-72 space-y-2">
      <div>
        <p className="text-sm font-medium">{t("agent.field.modelPriority")}</p>
        <p className="text-xs text-muted-foreground">
          {t("agent.field.modelPriorityHint")}
        </p>
      </div>
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleModelPriorityChange}
      >
        <SortableContext
          items={selectedModelIds}
          strategy={verticalListSortingStrategy}
        >
          <ul className="space-y-2">
            {selectedModels.map((model, index) =>
              model ? (
                <SortableModelItem
                  key={model.value}
                  modelId={model.value}
                  displayName={model.displayName}
                  isPrimary={index === 0}
                  disabled={isModelSelectionDisabled}
                  primaryLabel={t("agent.field.primaryModel")}
                  reorderLabel={t("agent.field.reorderModel")}
                />
              ) : null
            )}
          </ul>
        </SortableContext>
      </DndContext>
    </div>
  );

  const modelPriorityTrigger = (
    <Tooltip title={t("agent.field.adjustModelPriority")}>
      <span className="inline-flex">
        <Button
          type="default"
          icon={<ListOrdered size={16} />}
          aria-label={t("agent.field.adjustModelPriority")}
          disabled={selectedModels.length < 2 || isModelSelectionDisabled}
        />
      </span>
    </Tooltip>
  );

  const modelSelectionActions = (
    <div className="flex shrink-0 items-center gap-2">
      {selectedModels.length > 1 && !isModelSelectionDisabled ? (
        <Popover
          content={modelPriorityContent}
          trigger="click"
          placement="bottomRight"
          open={isModelPriorityOpen}
          onOpenChange={setIsModelPriorityOpen}
        >
          {modelPriorityTrigger}
        </Popover>
      ) : (
        modelPriorityTrigger
      )}
      <Tooltip
        title={t("agent.modelParamsOverride.button", {
          defaultValue: "模型参数覆盖",
        })}
      >
        <span className="inline-flex">
          <Button
            type="default"
            icon={<Settings2 size={16} />}
            aria-label={t("agent.modelParamsOverride.button", {
              defaultValue: "模型参数覆盖",
            })}
            disabled={
              isModelSelectionDisabled || !editedAgent.model_ids?.length
            }
            onClick={() =>
              setConfiguringModelId(editedAgent.model_ids?.[0] ?? null)
            }
          />
        </span>
      </Tooltip>
    </div>
  );

  const modelSelection = (
    <Row gutter={[12, 0]}>
      <Col xs={24} sm={24}>
        <Form.Item
          label={t("agent.field.model")}
          className="mb-3"
          layout="horizontal"
        >
          <div className="flex w-full items-start gap-2">
            <Form.Item
              noStyle
              name={highFidelity ? undefined : "model_ids"}
              rules={
                highFidelity
                  ? undefined
                  : [
                      {
                        required: true,
                        message: t("agent.validation.modelRequired"),
                      },
                    ]
              }
            >
              <Select
                className="min-w-0 flex-1"
                mode="multiple"
                placeholder={t("agent.field.modelPlaceholder")}
                options={modelOptions}
                value={selectedModelIds}
                onChange={updateModelSelection}
                maxTagCount={3}
                showSearch={{
                  filterOption: (input, option) =>
                    (option?.label ?? "")
                      .toLowerCase()
                      .includes(input.toLowerCase()),
                }}
                disabled={isModelSelectionDisabled}
              />
            </Form.Item>
            {modelSelectionActions}
          </div>
        </Form.Item>
      </Col>
    </Row>
  );

  const promptTabs = (
    <Tabs
      value={activePromptTab}
      onValueChange={handlePromptTabChange}
      className="relative z-0 w-full"
    >
      <TabsList className="grid w-full grid-cols-3">
        <TabsTrigger value="duty">{t("agent.field.dutyPrompt")}</TabsTrigger>
        <TabsTrigger value="constraint">
          {t("agent.field.constraintPrompt")}
        </TabsTrigger>
        <TabsTrigger value="few-shots">
          {t("agent.field.fewShotsPrompt")}
        </TabsTrigger>
      </TabsList>

      <TabsContent value="duty" className="mt-3">
        <Form.Item className="mb-0">
          <div className="relative">
            {highFidelity ? (
              <HighFidelityTextArea
                limit={1000}
                placeholder={t("agent.field.dutyPromptPlaceholder")}
                rows={6}
                value={editedAgent.duty_prompt ?? ""}
                disabled={isReadOnly}
                classNames={{
                  textarea: "!py-2 !pl-3 !pr-5",
                  count:
                    "!bottom-2 !right-3 !text-xs !leading-[22px] !text-[#808080]",
                }}
                onChange={(event) =>
                  updateDraft({ duty_prompt: event.target.value })
                }
              />
            ) : (
              <TextArea
                placeholder={t("agent.field.dutyPromptPlaceholder")}
                disabled={isReadOnly}
                rows={6}
                value={editedAgent.duty_prompt}
                style={{
                  paddingTop: 8,
                  paddingBottom: 8,
                  paddingLeft: 12,
                  paddingRight: 20,
                }}
                onChange={(event) =>
                  updateDraft({ duty_prompt: event.target.value })
                }
              />
            )}
            <div className="absolute right-1 top-2 z-10">
              {renderExpandButton("duty")}
            </div>
          </div>
        </Form.Item>
      </TabsContent>

      <TabsContent value="constraint" className="mt-3">
        <Form.Item className="mb-0">
          <div className="relative">
            <TextArea
              placeholder={t("agent.field.constraintPromptPlaceholder")}
              disabled={isReadOnly}
              rows={6}
              value={editedAgent.constraint_prompt}
              style={{
                paddingTop: 8,
                paddingBottom: 8,
                paddingLeft: 12,
                paddingRight: 20,
              }}
              onChange={(event) =>
                updateDraft({ constraint_prompt: event.target.value })
              }
            />
            <div className="absolute right-1 top-2 z-10">
              {renderExpandButton("constraint")}
            </div>
          </div>
        </Form.Item>
      </TabsContent>

      <TabsContent value="few-shots" className="mt-3">
        <Form.Item className="mb-0">
          <div className="relative">
            <TextArea
              placeholder={t("agent.field.fewShotsPromptPlaceholder")}
              disabled={isReadOnly}
              rows={6}
              value={editedAgent.few_shots_prompt}
              style={{
                paddingTop: 8,
                paddingBottom: 8,
                paddingLeft: 12,
                paddingRight: 20,
              }}
              onChange={(event) =>
                updateDraft({ few_shots_prompt: event.target.value })
              }
            />
            <div className="absolute right-1 top-2 z-10">
              {renderExpandButton("few-shots")}
            </div>
          </div>
        </Form.Item>
      </TabsContent>
    </Tabs>
  );

  return (
    <div className="w-full">
      {highFidelity ? (
        <div className="flex flex-col gap-4">
          <Form.Item
            name="model_ids"
            label={t("agent.highFidelity.modelSelection")}
            className="!mb-0"
            rules={[
              {
                required: true,
                message: t("agent.validation.modelRequired"),
              },
            ]}
          >
            <HighFidelityModelGrid
              selectedIds={selectedModelIds}
              models={availableLlmModels ?? []}
              disabled={isModelSelectionDisabled}
              onAddModel={() => setIsModelSelectionOpen(true)}
              onSelectionChange={updateModelSelection}
              onConfigureModel={setConfiguringModelId}
              reorderLabel={t("agent.field.reorderModel")}
              settingsLabel={t("agent.modelParamsOverride.button", {
                defaultValue: "模型参数覆盖",
              })}
              removeLabel={t("agent.highFidelity.removeModel")}
              textInferenceLabel={t("agent.highFidelity.modelCapability.text")}
              deepThinkingLabel={t(
                "agent.highFidelity.modelCapability.reasoning"
              )}
              toolCallsLabel={t("agent.highFidelity.modelCapability.tools")}
              addModelLabel={t("agent.highFidelity.addModel")}
              sensors={sensors}
            />
          </Form.Item>
          <div className="-mb-2 flex items-center gap-2 text-sm leading-[22px] tracking-[0px]">
            <label htmlFor="agent-primary-prompt" className="text-[#191919]">
              <span className="mr-1 text-[#f5222d]">*</span>
              {t("agent.highFidelity.prompt")}
            </label>
            <div className="flex items-center gap-2">
              <Tooltip title={t("agent.highFidelity.additionalPrompts")}>
                <Button
                  type="text"
                  className="!h-[22px] !w-[22px] !p-0"
                  icon={<Settings2 size={14} />}
                  aria-label={t("agent.highFidelity.additionalPrompts")}
                  disabled={false}
                  onClick={() => setAdditionalPromptsOpen(true)}
                />
              </Tooltip>
              <Button
                type="link"
                autoInsertSpace={false}
                className="!h-[22px] !p-0 !text-sm !leading-[22px] !text-[#2673e5] disabled:!text-[#dfdfdf]"
                icon={<Sparkles size={14} />}
                disabled={isReadOnly || !onOptimizePrompt}
                onClick={onOptimizePrompt}
              >
                {t("agent.highFidelity.optimizePrompt")}
              </Button>
            </div>
          </div>
          <div className="relative">
            <HighFidelityTextArea
              limit={1000}
              id="agent-primary-prompt"
              value={editedAgent.duty_prompt ?? ""}
              placeholder={t("agent.highFidelity.promptPlaceholder")}
              disabled={isReadOnly}
              classNames={{
                textarea:
                  "!h-[52px] !min-h-[52px] !resize-none !rounded-[4px] !py-[5px] !pl-3 !pr-8 !text-sm !leading-[22px] !tracking-[0px] !text-[#191919] [font-family:'HarmonyOS_Sans_SC',sans-serif]",
                count:
                  "!bottom-2 !right-3 !text-xs !leading-[22px] !text-[#808080]",
              }}
              onChange={(event) =>
                updateDraft({ duty_prompt: event.target.value })
              }
            />
            <div className="absolute right-1 top-2">
              {renderExpandButton("duty")}
            </div>
          </div>
          <Modal
            open={additionalPromptsOpen}
            title={t("agent.highFidelity.additionalPrompts")}
            onCancel={() => setAdditionalPromptsOpen(false)}
            footer={null}
            centered
            forceRender
          >
            {promptTabs}
          </Modal>
          <AddModelDrawer
            open={isModelSelectionOpen}
            onClose={() => setIsModelSelectionOpen(false)}
            models={availableLlmModels ?? []}
            selectedModelIds={selectedModelIds}
            selectedTrailing={modelSelectionActions}
            disabled={isModelSelectionDisabled}
            onSelectionChange={(ids) => {
              if (isModelSelectionDisabled) return;
              form.setFieldValue("model_ids", ids);
              updateModelSelection(ids);
            }}
          />
        </div>
      ) : (
        <>
          {modelSelection}
          {promptTabs}
        </>
      )}

      {expandedPrompt &&
        (highFidelity && expandedPrompt === "duty" ? (
          <HighFidelityPromptEditModal
            key={`${agentId}-${expandedPrompt}`}
            title={expandedPromptConfig[expandedPrompt].title}
            content={expandedPromptConfig[expandedPrompt].content}
            readOnly={isReadOnly}
            onClose={() => setExpandedPrompt(null)}
            onSave={(content) => {
              if (!isReadOnly)
                expandedPromptConfig[expandedPrompt].save(content);
            }}
          />
        ) : (
          <ExpandEditModal
            open
            title={expandedPromptConfig[expandedPrompt].title}
            content={expandedPromptConfig[expandedPrompt].content}
            onClose={() => setExpandedPrompt(null)}
            onSave={(content) => {
              if (!isReadOnly)
                expandedPromptConfig[expandedPrompt].save(content);
            }}
          />
        ))}

      {/* v2.6.0: per-model parameter override popup */}
      <Modal
        open={configuringModelId !== null}
        onCancel={() => setConfiguringModelId(null)}
        onOk={() => {
          if (editingOverrideValue && configuringModel) {
            const modelDefaults = advancedSettingsValueFromRecord(
              {
                temperature: (configuringModel as any).temperature,
                top_p: (configuringModel as any).topP,
                extra_params: (configuringModel as any).extraParams,
                reasoning_capability: (configuringModel as any)
                  .reasoningCapability,
              },
              inferenceSpecs,
              (configuringModel as any).type ?? "llm",
              (configuringModel as any).reasoningCapability
            );
            const diffValue: ModelAdvancedSettingsValue = {};
            for (const [key, val] of Object.entries(editingOverrideValue)) {
              // Custom params are diffed per-key below (deleting an
              // inherited row must persist a removal, not drop the key).
              if (key === "__custom__") continue;
              // Reasoning is an agent-owned snapshot under Scheme B. It must
              // not be compared with the current model-level setting.
              if (
                key === "enable_thinking" ||
                key === "reasoning_effort" ||
                key === "reasoning_budget_tokens"
              ) {
                diffValue[key] = val;
                continue;
              }
              const modelVal = modelDefaults[key];
              if (JSON.stringify(modelVal) !== JSON.stringify(val)) {
                diffValue[key] = val;
              }
            }
            const customDiff = diffCustomParamsForSave(
              editingOverrideValue.__custom__,
              (configuringModel as any).extraParams?.__custom__
            );
            if (Object.keys(customDiff).length > 0) {
              diffValue.__custom__ = customDiff;
            }
            handleModelParamsOverrideChange(configuringModel.id, diffValue);
          }
          setConfiguringModelId(null);
        }}
        title={
          configuringModel
            ? `${configuringModel.displayName ?? configuringModel.name} - ${t("model.advanced.overrideTitle", { defaultValue: "模型参数覆盖" })}`
            : t("model.advanced.overrideTitle", {
                defaultValue: "模型参数覆盖",
              })
        }
        okText={t("common.confirm", { defaultValue: "确定" })}
        cancelText={t("common.cancel", { defaultValue: "取消" })}
        okButtonProps={{ disabled: isModelSelectionDisabled }}
        width={600}
        centered
        destroyOnHidden={false}
        styles={{ body: { maxHeight: "60vh", overflowY: "auto" } }}
      >
        {configuringModel && (
          <div className="space-y-3">
            <Select
              className="mb-2 w-full"
              value={configuringModelId}
              options={modelOptions}
              onChange={(v: number) => setConfiguringModelId(v)}
              disabled={isModelSelectionDisabled}
            />
            <ModelAdvancedSettings
              modelType={(configuringModel as any).type ?? "llm"}
              specs={Object.fromEntries(
                Object.entries(inferenceSpecs).map(([type, specs]) => [
                  type,
                  (specs as any[]).filter((s) => s.key !== "tokenizer_family"),
                ])
              )}
              value={
                editingOverrideValue ??
                advancedSettingsValueFromRecord(
                  {},
                  inferenceSpecs,
                  (configuringModel as any).type ?? "llm",
                  (configuringModel as any).reasoningCapability
                )
              }
              onChange={(next) => setEditingOverrideValue(next)}
              mode="override"
              disabled={isModelSelectionDisabled}
              reasoningCapability={
                (configuringModel as any).reasoningCapability
              }
              // Show the model-level defaults as placeholders so "empty =
              // inherit" is visible (the override form starts blank).
              inheritedDefaults={{
                display_name:
                  configuringModel.displayName ?? configuringModel.name,
                context_window_tokens: (configuringModel as any)
                  .contextWindowTokens,
                max_input_tokens: (configuringModel as any).maxInputTokens,
                max_output_tokens: (configuringModel as any).maxOutputTokens,
                default_output_reserve_tokens: (configuringModel as any)
                  .defaultOutputReserveTokens,
                temperature: (configuringModel as any).temperature,
                top_p: (configuringModel as any).topP,
              }}
            />
          </div>
        )}
      </Modal>
    </div>
  );
}

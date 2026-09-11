"use client";

import { useTranslation } from "react-i18next";
import { Button, Col, Form, Input, Popover, Row, Select, Tooltip } from "antd";
import { GripVertical, ListOrdered, Maximize2 } from "lucide-react";
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
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import { useAgentStore } from "@/stores/agentStore";
import { useModelList } from "@/hooks/model/useModelList";
import { canManageModels } from "@/lib/auth";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { useNl2AgentFlow } from "@/contexts/nl2AgentFlow";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import ExpandEditModal from "@/components/common/ExpandEditModal";
import {
  reorderModelIds,
  resolveModelSelection,
} from "@/lib/agent/modelPriority";

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

export default function AgentPrompt() {
  const { t } = useTranslation("common");
  const form = Form.useFormInstance();
  const { user } = useAuthorizationContext();
  const { availableLlmModels, isSuccess: modelListLoaded } = useModelList();
  const { isSpeedMode } = useDeployment();
  const editedAgent = useAgentStore((state) => state.editedAgent!);
  const updateDraft = useAgentStore((state) => state.updateDraft);
  const flushDraft = useAgentStore((state) => state.flushDraft);
  const updateAgent = useAgentStore((state) => state.updateAgentConfig);
  const agentId = useAgentStore((state) => state.agentId);
  const defaultLlmConfig = useAgentStore((state) => state.defaultLlmConfig);
  const { configFocusRequest } = useNl2AgentFlow();

  const [expandedPrompt, setExpandedPrompt] = useState<PromptTab | null>(null);
  const [activePromptTab, setActivePromptTab] = useState<PromptTab>("duty");
  const [isModelPriorityOpen, setIsModelPriorityOpen] = useState(false);
  const requestedPromptTab =
    configFocusRequest?.agentId === agentId &&
    configFocusRequest.target.section === "role_model"
      ? configFocusRequest.target.promptTab
      : null;

  useEffect(() => {
    setActivePromptTab("duty");
  }, [agentId]);

  useEffect(() => {
    if (requestedPromptTab) setActivePromptTab(requestedPromptTab);
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
    const configuredModelIds = editedAgent.model_ids ?? [];
    if (configuredModelIds.length > 0) {
      return configuredModelIds.filter((id) => availableModelIds.has(id));
    }
    return defaultLlmConfig?.id && availableModelIds.has(defaultLlmConfig.id)
      ? [defaultLlmConfig.id]
      : [];
  }, [availableModelIds, defaultLlmConfig?.id, editedAgent.model_ids]);

  useEffect(() => {
    if (!modelListLoaded || !editedAgent.model_ids?.length) return;

    const nextModelIds = editedAgent.model_ids.filter((id) =>
      availableModelIds.has(id)
    );
    if (nextModelIds.length === editedAgent.model_ids.length) return;

    const modelNames = nextModelIds.map((id) => {
      const option = modelOptions.find((model) => model.value === id);
      return option?.displayName ?? "";
    });
    const primaryModel = modelOptions.find(
      (option) => option.value === nextModelIds[0]
    );
    updateAgent({
      model_ids: nextModelIds,
      model: primaryModel?.displayName ?? "",
      model_names: modelNames,
    });
  }, [
    availableModelIds,
    editedAgent.model_ids,
    modelListLoaded,
    modelOptions,
    updateAgent,
  ]);

  const canManage = canManageModels(user?.role ?? "");
  const isModelSelectionDisabled = !canManage && !isSpeedMode;
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

  return (
    <div className="w-full">
      {/* Model Selection */}
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
                name="model_ids"
                rules={[
                  {
                    required: true,
                    message: t("agent.validation.modelRequired"),
                  },
                ]}
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
            </div>
          </Form.Item>
        </Col>
      </Row>

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
              <TextArea
                placeholder={t("agent.field.dutyPromptPlaceholder")}
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

      {expandedPrompt && (
        <ExpandEditModal
          open
          title={expandedPromptConfig[expandedPrompt].title}
          content={expandedPromptConfig[expandedPrompt].content}
          onClose={() => setExpandedPrompt(null)}
          onSave={(content) =>
            expandedPromptConfig[expandedPrompt].save(content)
          }
        />
      )}
    </div>
  );
}

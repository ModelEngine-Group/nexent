"use client";

import { useTranslation } from "react-i18next";
import { Button, Col, Form, Input, Row, Select, Tooltip } from "antd";
import { Maximize2 } from "lucide-react";

import { useAgentStore } from "@/stores/agentStore";
import { useModelList } from "@/hooks/model/useModelList";
import { canManageModels } from "@/lib/auth";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import ExpandEditModal from "./basic/ExpandEditModal";

const { TextArea } = Input;

type PromptTab = "duty" | "constraint" | "few-shots";

interface AgentPromptProps {
  focusRequest?: {
    requestId: number;
    promptTab: PromptTab;
  } | null;
}

export default function AgentPrompt({ focusRequest = null }: AgentPromptProps) {
  const { t } = useTranslation("common");
  const { user } = useAuthorizationContext();
  const { llmModels } = useModelList();
  const { isSpeedMode } = useDeployment();
  const editedAgent = useAgentStore((state) => state.editedAgent!);
  const updateDraft = useAgentStore((state) => state.updateDraft);
  const flushDraft = useAgentStore((state) => state.flushDraft);
  const updateAgent = useAgentStore((state) => state.updateAgentConfig);
  const agentId = useAgentStore((state) => state.agentId);
  const defaultLlmConfig = useAgentStore((state) => state.defaultLlmConfig);

  const [expandedPrompt, setExpandedPrompt] = useState<PromptTab | null>(null);
  const [activePromptTab, setActivePromptTab] = useState<PromptTab>("duty");
  const requestedPromptTab = focusRequest?.promptTab;
  const focusRequestId = focusRequest?.requestId;

  useEffect(() => {
    setActivePromptTab("duty");
  }, [agentId]);

  useEffect(() => {
    if (requestedPromptTab) setActivePromptTab(requestedPromptTab);
  }, [focusRequestId, requestedPromptTab]);

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
    return (llmModels ?? []).map((m) => ({
      value: m.id,
      label: m.displayName ?? m.name,
      model_name: m.name,
    }));
  }, [llmModels]);

  const canManage = canManageModels(user?.role ?? "");

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

  return (
    <div className="w-full">
      {/* Model Selection */}
      <Row gutter={[12, 0]}>
        <Col xs={24} sm={24}>
          <Form.Item
            label={t("agent.field.model")}
            className="mb-3"
            layout="horizontal"
            name="model_ids"
            rules={[
              {
                required: true,
                message: t("agent.validation.modelRequired"),
              },
            ]}
          >
            <Select
              mode="multiple"
              placeholder={t("agent.field.modelPlaceholder")}
              options={modelOptions}
              value={
                editedAgent.model_ids?.length
                  ? editedAgent.model_ids
                  : defaultLlmConfig?.id
                    ? [defaultLlmConfig.id]
                    : []
              }
              onChange={(values: number[]) => {
                const model_names = values.map((id) => {
                  const option = modelOptions.find((opt) => opt.value === id);
                  return option?.model_name ?? "";
                });
                const primaryModel = modelOptions.find(
                  (option) => option.value === values[0]
                );
                updateAgent({
                  model_ids: values,
                  model: primaryModel?.model_name ?? "",
                  model_names,
                });
              }}
              maxTagCount={3}
              showSearch
              filterOption={(input, option) =>
                (option?.label ?? "")
                  .toLowerCase()
                  .includes(input.toLowerCase())
              }
              disabled={!canManage && !isSpeedMode}
            />
          </Form.Item>
        </Col>
      </Row>

      <Tabs
        value={activePromptTab}
        onValueChange={handlePromptTabChange}
        className="w-full"
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

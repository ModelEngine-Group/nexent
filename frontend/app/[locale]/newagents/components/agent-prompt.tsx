"use client";

import { useTranslation } from "react-i18next";
import { Form, Input, Select, Row, Col } from "antd";

import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { useAgentStore } from "@/stores/agentStore";
import { useModelList } from "@/hooks/model/useModelList";
import { canManageModels } from "@/lib/auth";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { useCallback, useMemo } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const { TextArea } = Input;

export default function AgentPrompt() {
  const { t } = useTranslation("common");
  const { user } = useAuthorizationContext();
  const { models } = useModelList();
  const { isSpeedMode } = useDeployment();
  const editedAgent = useAgentStore((state) => state.editedAgent!);
  const updateDraft = useAgentStore((state) => state.updateDraft);
  const flushDraft = useAgentStore((state) => state.flushDraft);
  const updateAgent = useAgentStore((state) => state.updateAgentConfig);
  const defaultLlmConfig = useAgentConfigStore(
    (state) => state.defaultLlmConfig
  );

  const handlePromptTabChange = useCallback(() => {
    flushDraft();
  }, [flushDraft]);

  const modelOptions = useMemo(() => {
    return (models ?? []).map((m: any) => ({
      value: m.id,
      label: m.display_name ?? m.name,
      model_name: m.name,
    }));
  }, [models]);

  const canManage = canManageModels(user?.role ?? "");

  return (
    <div className="w-full">
      {/* Model Selection */}
      <Row gutter={[12, 0]}>
        <Col xs={24} sm={12}>
          <Form.Item
            label={t("agent.field.model")}
            className="mb-3"
            layout="horizontal"
          >
            <Select
              placeholder={t("agent.field.modelPlaceholder")}
              options={modelOptions}
              value={editedAgent.model_ids?.[0] ?? defaultLlmConfig?.id}
              onChange={(val, opt) => {
                updateAgent({
                  model_ids: val ? [val] : [],
                  model: (opt as any)?.model_name ?? "",
                });
              }}
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
        defaultValue="duty"
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
            <TextArea
              placeholder={t("agent.field.dutyPromptPlaceholder")}
              rows={6}
              value={editedAgent.duty_prompt}
              onChange={(event) =>
                updateDraft({ duty_prompt: event.target.value })
              }
            />
          </Form.Item>
        </TabsContent>

        <TabsContent value="constraint" className="mt-3">
          <Form.Item className="mb-0">
            <TextArea
              placeholder={t("agent.field.constraintPromptPlaceholder")}
              rows={6}
              value={editedAgent.constraint_prompt}
              onChange={(event) =>
                updateDraft({ constraint_prompt: event.target.value })
              }
            />
          </Form.Item>
        </TabsContent>

        <TabsContent value="few-shots" className="mt-3">
          <Form.Item className="mb-0">
            <TextArea
              placeholder={t("agent.field.fewShotsPromptPlaceholder")}
              rows={6}
              value={editedAgent.few_shots_prompt}
              onChange={(event) =>
                updateDraft({ few_shots_prompt: event.target.value })
              }
            />
          </Form.Item>
        </TabsContent>
      </Tabs>
    </div>
  );
}

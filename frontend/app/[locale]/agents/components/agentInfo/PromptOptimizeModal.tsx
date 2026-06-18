import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { App, Button, Card, Input, Modal, Space, Typography } from "antd";

import log from "@/lib/logger";
import { optimizePromptSection } from "@/services/promptService";
import type { OptimizePromptSectionResponse } from "@/types/agentConfig";

const { TextArea } = Input;
const { Paragraph, Text } = Typography;

export interface PromptOptimizeModalProps {
  open: boolean;
  title: string;
  sectionType: "duty" | "constraint" | "few_shots";
  taskDescription: string;
  currentContent: string;
  modelId: number;
  agentId: number;
  toolIds: number[];
  subAgentIds: number[];
  knowledgeBaseDisplayNames?: string[];
  onClose: () => void;
  onReplace: (content: string) => void;
}

export default function PromptOptimizeModal({
  open,
  title,
  sectionType,
  taskDescription,
  currentContent,
  modelId,
  agentId,
  toolIds,
  subAgentIds,
  knowledgeBaseDisplayNames,
  onClose,
  onReplace,
}: PromptOptimizeModalProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const [feedback, setFeedback] = useState("");
  const [optimizedContent, setOptimizedContent] = useState("");
  const [isOptimizing, setIsOptimizing] = useState(false);

  useEffect(() => {
    if (!open) {
      setFeedback("");
      setOptimizedContent("");
      setIsOptimizing(false);
      return;
    }

    setFeedback("");
    setOptimizedContent("");
  }, [open, sectionType, currentContent]);

  const handleOptimize = async () => {
    if (!feedback.trim()) {
      message.error(t("systemPrompt.optimize.feedbackRequired"));
      return;
    }

    setIsOptimizing(true);
    try {
      const result: OptimizePromptSectionResponse = await optimizePromptSection({
        agent_id: agentId,
        task_description: taskDescription,
        model_id: String(modelId),
        section_type: sectionType,
        section_title: title,
        current_content: currentContent,
        feedback,
        tool_ids: toolIds,
        sub_agent_ids: subAgentIds,
        knowledge_base_display_names: knowledgeBaseDisplayNames,
      });
      setOptimizedContent(result.optimized_content || "");
    } catch (error: any) {
      log.error("Optimize prompt section failed:", error);
      message.error(error?.message || t("systemPrompt.optimize.error"));
    } finally {
      setIsOptimizing(false);
    }
  };

  const handleReplace = () => {
    if (!optimizedContent.trim()) {
      return;
    }
    onReplace(optimizedContent);
  };

  return (
    <Modal
      title={title}
      open={open}
      onCancel={onClose}
      width={1200}
      footer={
        <Space>
          <Button onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            type="primary"
            onClick={handleReplace}
            disabled={!optimizedContent.trim() || isOptimizing}
          >
            {t("systemPrompt.optimize.replace")}
          </Button>
        </Space>
      }
      destroyOnHidden
    >
      <div className="flex flex-col gap-4">
        <div>
          <Text strong>{t("systemPrompt.optimize.feedbackLabel")}</Text>
          <TextArea
            value={feedback}
            onChange={(event) => setFeedback(event.target.value)}
            placeholder={t("systemPrompt.optimize.feedbackPlaceholder")}
            rows={4}
            className="mt-2"
            disabled={isOptimizing}
          />
        </div>

        <div className="flex justify-end">
          <Button
            type="primary"
            onClick={handleOptimize}
            loading={isOptimizing}
          >
            {t("systemPrompt.optimize.submit")}
          </Button>
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Card title={t("systemPrompt.optimize.original")}>
            <Paragraph
              style={{ whiteSpace: "pre-wrap", minHeight: 320, marginBottom: 0 }}
            >
              {currentContent || t("common.none")}
            </Paragraph>
          </Card>
          <Card title={t("systemPrompt.optimize.optimized")}>
            <Paragraph
              style={{ whiteSpace: "pre-wrap", minHeight: 320, marginBottom: 0 }}
            >
              {optimizedContent || t("systemPrompt.optimize.empty")}
            </Paragraph>
          </Card>
        </div>
      </div>
    </Modal>
  );
}

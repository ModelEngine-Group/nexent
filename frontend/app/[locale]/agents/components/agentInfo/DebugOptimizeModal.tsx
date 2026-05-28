"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { App, Button, Input, Modal, Space, Typography } from "antd";

const { TextArea } = Input;
const { Paragraph, Text } = Typography;

export interface DebugOptimizeModalProps {
  open: boolean;
  agentId: number;
  modelId: number;
  userQuestion: string;
  assistantAnswer: string;
  history: Array<{ role: string; content: string }>;
  onCancel: () => void;
  onOptimized: (params: { originalFullPrompt: string; optimizedFullPrompt: string }) => void;
}

export default function DebugOptimizeModal({
  open,
  agentId,
  modelId,
  userQuestion,
  assistantAnswer,
  history,
  onCancel,
  onOptimized,
}: DebugOptimizeModalProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();

  const [feedback, setFeedback] = useState("");
  const [isOptimizing, setIsOptimizing] = useState(false);

  useEffect(() => {
    if (!open) {
      setFeedback("");
      setIsOptimizing(false);
      return;
    }
    setFeedback("");
    setIsOptimizing(false);
  }, [open, agentId, modelId]);

  const handleOk = async () => {
    if (!feedback.trim()) {
      message.error(t("systemPrompt.optimize.feedbackRequired"));
      return;
    }

    setIsOptimizing(true);
    try {
      const resp = await fetch("/api/prompt/optimize/from_debug", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          agent_id: agentId,
          model_id: modelId,
          feedback: feedback.trim(),
          selected: {
            user_question: userQuestion,
            assistant_answer: assistantAnswer,
          },
          history,
        }),
      });

      const result = await resp.json();
      if (!resp.ok) {
        throw new Error(result?.message || t("systemPrompt.optimize.error"));
      }

      const data = result?.data;
      onOptimized({
        originalFullPrompt: data?.original_full_prompt || "",
        optimizedFullPrompt: data?.optimized_full_prompt || "",
      });
    } catch (e: any) {
      message.error(e?.message || t("systemPrompt.optimize.error"));
    } finally {
      setIsOptimizing(false);
    }
  };

  return (
    <Modal
      title={t("agent.debug.optimizeTitle", "Optimize prompt")}
      open={open}
      onCancel={onCancel}
      width={720}
      footer={
        <Space>
          <Button onClick={onCancel}>{t("common.cancel")}</Button>
          <Button type="primary" onClick={handleOk} loading={isOptimizing}>
            {t("systemPrompt.optimize.submit")}
          </Button>
        </Space>
      }
      destroyOnHidden
    >
      <div className="flex flex-col gap-3">
        <Text type="secondary">
          {t("agent.debug.optimizeHint", "Select a reply, provide feedback, and we will optimize the full system prompt.")}
        </Text>
        <div>
          <Text strong>{t("systemPrompt.optimize.feedbackLabel")}</Text>
          <TextArea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder={t("systemPrompt.optimize.feedbackPlaceholder")}
            rows={4}
            className="mt-2"
            disabled={isOptimizing}
          />
        </div>

        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <div>
            <Text type="secondary" className="text-xs">
              {t("agent.debug.selectedQuestion", "Selected question")}
            </Text>
            <Paragraph style={{ whiteSpace: "pre-wrap" }} className="text-sm">
              {userQuestion || t("common.none")}
            </Paragraph>
          </div>
          <div>
            <Text type="secondary" className="text-xs">
              {t("agent.debug.selectedAnswer", "Selected answer")}
            </Text>
            <Paragraph style={{ whiteSpace: "pre-wrap" }} className="text-sm">
              {assistantAnswer || t("common.none")}
            </Paragraph>
          </div>
        </div>
      </div>
    </Modal>
  );
}

"use client";

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { App, Button, Input, Modal, Space, Spin, Typography } from "antd";

const { TextArea } = Input;
const { Paragraph, Text } = Typography;

export interface DebugOptimizeModalProps {
  open: boolean;
  agentId: number;
  modelId: number;
  userQuestion: string;
  assistantAnswer: string;
  history: Array<{ role: string; content: string }>;
  initialOriginalFullPrompt?: string;
  onCancel: () => void;
  onOptimized: (params: { originalFullPrompt: string; optimizedFullPrompt: string }) => void;
  onApply: (optimizedFullPrompt: string) => void;
  applying?: boolean;
}

export default function DebugOptimizeModal({
  open,
  agentId,
  modelId,
  userQuestion,
  assistantAnswer,
  history,
  initialOriginalFullPrompt,
  onCancel,
  onOptimized,
  onApply,
  applying,
}: DebugOptimizeModalProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();

  const [feedback, setFeedback] = useState("");
  const [isOptimizing, setIsOptimizing] = useState(false);

  const [originalFullPrompt, setOriginalFullPrompt] = useState("");
  const [optimizedFullPrompt, setOptimizedFullPrompt] = useState("");
  const [displayedContent, setDisplayedContent] = useState("");

  // Section header mapping: English -> Chinese
  const headerMap: Record<string, string> = {
    "# Duty": "#智能体角色",
    "# Constraint": "#使用要求",
    "# FewShots": "#示例",
  };

  const mapHeadersToChinese = (text: string) => {
    let result = text;
    for (const [en, zh] of Object.entries(headerMap)) {
      result = result.split(en).join(zh);
    }
    return result;
  };

  useEffect(() => {
    if (!open) {
      setFeedback("");
      setIsOptimizing(false);
      setOriginalFullPrompt("");
      setOptimizedFullPrompt("");
      setDisplayedContent("");
      return;
    }

    setFeedback("");
    setIsOptimizing(false);
    setDisplayedContent("");
    // Show original prompt immediately when opening the modal.
    setOriginalFullPrompt((prev) => prev || initialOriginalFullPrompt || "");
    // Keep original prompt visible while waiting for new optimized result.
    setOptimizedFullPrompt("");
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
      const original = data?.original_full_prompt || "";
      const fullText = mapHeadersToChinese(data?.optimized_full_prompt || "");

      setOriginalFullPrompt(original);
      setOptimizedFullPrompt(fullText);
      setDisplayedContent(fullText);

      // Ensure modal stays open and does not reset prompts.
      setIsOptimizing(false);

      onOptimized({
        originalFullPrompt: original,
        optimizedFullPrompt: fullText,
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
      width={1200}
      footer={
        <Space>
          <Button onClick={onCancel}>{t("common.cancel")}</Button>
          <Button
            type="primary"
            onClick={() => onApply(optimizedFullPrompt)}
            disabled={!optimizedFullPrompt.trim()}
            loading={applying}
          >
            {t("agent.debug.promptCompare.apply", "Apply")}
          </Button>
          <Button type="primary" onClick={handleOk}>
            {t("systemPrompt.optimize.submit")}
          </Button>
        </Space>
      }
      destroyOnHidden
    >
      <div className="flex flex-col gap-3">
        <Text type="secondary">
          {t(
            "agent.debug.optimizeHint",
            "Select a reply, provide feedback, and we will optimize the full system prompt."
          )}
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
            <Text strong>{t("agent.debug.selectedQuestion", "Selected question")}</Text>
            <div className="mt-2 border border-gray-200 rounded-md p-3 bg-gray-50">
              <Paragraph style={{ whiteSpace: "pre-wrap", marginBottom: 0 }} className="text-sm">
                {userQuestion || t("common.none")}
              </Paragraph>
            </div>
          </div>
          <div>
            <Text strong>{t("agent.debug.selectedAnswer", "Selected answer")}</Text>
            <div className="mt-2 border border-gray-200 rounded-md p-3 bg-gray-50">
              <Paragraph style={{ whiteSpace: "pre-wrap", marginBottom: 0 }} className="text-sm">
                {assistantAnswer || t("common.none")}
              </Paragraph>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div>
            <Text strong>{t("agent.debug.promptCompare.original", "Original")}</Text>
            <div className="mt-2 border border-gray-200 rounded-md p-3 bg-gray-50">
              <Paragraph
                style={{ whiteSpace: "pre-wrap", minHeight: 520, marginBottom: 0 }}
                className="font-mono text-sm"
              >
                {mapHeadersToChinese(originalFullPrompt) || "-"}
              </Paragraph>
            </div>
          </div>
          <div>
            <Text strong>{t("agent.debug.promptCompare.optimized", "Optimized")}</Text>
            <div className="mt-2 border border-gray-200 rounded-md p-3">
              {isOptimizing ? (
                <div className="flex flex-col items-center justify-center gap-3" style={{ minHeight: 520 }}>
                  <Spin size="medium" />
                  <span className="text-gray-500 text-sm">
                    {t("systemPrompt.optimize.generating")}
                  </span>
                </div>
              ) : (
                <Paragraph
                  style={{ whiteSpace: "pre-wrap", minHeight: 520, marginBottom: 0 }}
                  className="font-mono text-sm"
                >
                  {displayedContent || t("systemPrompt.optimize.empty")}
                </Paragraph>
              )}
            </div>
          </div>
        </div>
      </div>
    </Modal>
  );
}

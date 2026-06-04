"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useTranslation } from "react-i18next";
import {
  App,
  Button,
  Card,
  Input,
  Modal,
  Radio,
  Space,
  Spin,
  Typography,
  Divider,
  Tooltip,
  Alert,
} from "antd";
import { MousePointer2 } from "lucide-react";

import log from "@/lib/logger";
import { optimizePromptSection } from "@/services/promptService";
import type { OptimizePromptSectionResponse } from "@/types/agentConfig";

const { TextArea } = Input;
const { Paragraph, Text } = Typography;

export type OptimizeMode = "general" | "insert" | "select";

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
  onReplace: (content: string, sectionType: "duty" | "constraint" | "few_shots") => void;
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
  const [mode, setMode] = useState<OptimizeMode>("general");
  const [feedback, setFeedback] = useState("");
  const [startPos, setStartPos] = useState<string>("");
  const [endPos, setEndPos] = useState<string>("");
  const [optimizedContent, setOptimizedContent] = useState("");
  const [isOptimizing, setIsOptimizing] = useState(false);
  const [isContentSelected, setIsContentSelected] = useState(false);
  const contentTextAreaRef = useRef<any>(null);

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
      setOptimizedContent("");
      setIsOptimizing(false);
      setMode("general");
      setStartPos("");
      setEndPos("");
      setIsContentSelected(false);
      return;
    }
    setFeedback("");
    setOptimizedContent("");
    setIsOptimizing(false);
    setMode("general");
    setStartPos("");
    setEndPos("");
    setIsContentSelected(false);
  }, [open, sectionType, currentContent]);

  const handleContentSelect = useCallback(() => {
    if (!contentTextAreaRef.current) return;
    const textarea = contentTextAreaRef.current.resizableTextArea?.textArea;
    if (!textarea) return;

    const { selectionStart, selectionEnd } = textarea;

    // Insert mode: allow caret position even when no range is selected
    if (selectionStart === selectionEnd) {
      setStartPos(String(selectionStart));
      setEndPos("");
      setIsContentSelected(false);
      setMode("insert");
      return;
    }

    // Select mode: range selected
    setStartPos(String(selectionStart));
    setEndPos(String(selectionEnd));
    setIsContentSelected(true);
    setMode("select");
  }, []);

  const handleOptimize = async () => {
    if (!feedback.trim()) {
      message.error(t("systemPrompt.optimize.feedbackRequired"));
      return;
    }

    if (mode === "insert") {
      const pos = parseInt(startPos, 10);
      if (isNaN(pos) || pos < 0) {
        message.error(t("systemPrompt.finetune.positionError"));
        return;
      }
    }

    if (mode === "select") {
      const start = parseInt(startPos, 10);
      const end = parseInt(endPos, 10);
      if (isNaN(start) || isNaN(end) || start < 0 || end < 0 || start >= end) {
        message.error(t("systemPrompt.finetune.positionError"));
        return;
      }
    }

    setIsOptimizing(true);
    try {
      const result: OptimizePromptSectionResponse = await optimizePromptSection({
        agent_id: agentId,
        task_description: taskDescription,
        model_id: modelId,
        section_type: sectionType,
        section_title: title,
        current_content: currentContent,
        feedback,
        mode,
        start_pos: mode !== "general" ? parseInt(startPos, 10) : undefined,
        end_pos: mode === "select" ? parseInt(endPos, 10) : undefined,
        tool_ids: toolIds,
        sub_agent_ids: subAgentIds,
        knowledge_base_display_names: knowledgeBaseDisplayNames,
      });
      const fullText = mapHeadersToChinese(result.optimized_content || "");
      setOptimizedContent(fullText);
    } catch (error: any) {
      log.error("Optimize prompt section failed:", error);
      message.error(error?.message || t("systemPrompt.optimize.error"));
    } finally {
      setIsOptimizing(false);
    }
  };

  const handleReplace = () => {
    if (!optimizedContent.trim() || isOptimizing) return;
    onReplace(optimizedContent.trim(), sectionType);
  };

  const modeOptions: Array<{ value: OptimizeMode; label: string; desc: string }> = [
    {
      value: "general",
      label: t("systemPrompt.finetune.modeGeneral"),
      desc: t("systemPrompt.finetune.modeGeneralDesc"),
    },
    {
      value: "insert",
      label: t("systemPrompt.finetune.modeInsert"),
      desc: t("systemPrompt.finetune.modeInsertDesc"),
    },
    {
      value: "select",
      label: t("systemPrompt.finetune.modeSelect"),
      desc: t("systemPrompt.finetune.modeSelectDesc"),
    },
  ];

  return (
    <Modal
      title={title}
      open={open}
      onCancel={onClose}
      width={1200}
      footer={
        <Space>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
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
        {/* Mode Selection */}
        <div>
          <Text strong className="mb-2 block">
            {t("systemPrompt.finetune.modeLabel")}
          </Text>
          <Radio.Group
            value={mode}
            onChange={(e) => setMode(e.target.value)}
            className="flex flex-col gap-2"
          >
            {modeOptions.map((opt) => (
              <Radio key={opt.value} value={opt.value} className="!ml-0">
                <span className="font-medium">{opt.label}</span>
                <span className="text-gray-500 text-sm ml-2">{opt.desc}</span>
              </Radio>
            ))}
          </Radio.Group>
        </div>

        {/* Position inputs for insert/select modes */}
        {mode !== "general" && (
          <div className="bg-gray-50 rounded-md p-4">
            {mode === "insert" && (
              <div className="flex items-center gap-4">
                <div className="flex-1">
                  <Text type="secondary" className="text-xs">
                    {t("systemPrompt.finetune.insertPositionLabel")}
                  </Text>
                  <Input
                    type="number"
                    min={0}
                    value={startPos}
                    onChange={(e) => setStartPos(e.target.value)}
                    placeholder={t("systemPrompt.finetune.insertPositionPlaceholder")}
                  />
                </div>
              </div>
            )}
            {mode === "select" && (
              <div className="flex items-center gap-4 flex-wrap">
                <div>
                  <Text type="secondary" className="text-xs">
                    {t("systemPrompt.finetune.selectStartLabel")}
                  </Text>
                  <Input
                    type="number"
                    min={0}
                    value={startPos}
                    onChange={(e) => setStartPos(e.target.value)}
                    placeholder={t("systemPrompt.finetune.selectStartPlaceholder")}
                    style={{ width: 140 }}
                  />
                </div>
                <div>
                  <Text type="secondary" className="text-xs">
                    {t("systemPrompt.finetune.selectEndLabel")}
                  </Text>
                  <Input
                    type="number"
                    min={0}
                    value={endPos}
                    onChange={(e) => setEndPos(e.target.value)}
                    placeholder={t("systemPrompt.finetune.selectEndPlaceholder")}
                    style={{ width: 140 }}
                  />
                </div>
              </div>
            )}
            {isContentSelected && (
              <Alert
                title={
                  <span className="text-xs">
                    {t("systemPrompt.finetune.selectTip")}: {startPos} - {endPos}
                  </span>
                }
                type="success"
                showIcon
                className="mt-2"
              />
            )}
          </div>
        )}

        <Divider className="my-2" />

        {/* Feedback Input */}
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

        {/* Submit Button */}
        <div className="flex justify-end">
          <Button type="primary" onClick={handleOptimize}>
            {t("systemPrompt.optimize.submit")}
          </Button>
        </div>

        {/* Before/After Comparison */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Card
            title={
              <div className="flex items-center justify-between">
                <span>{t("systemPrompt.optimize.original")}</span>
                <Tooltip title={t("systemPrompt.finetune.selectTip")}>
                  <Button
                    size="small"
                    type="text"
                    icon={<MousePointer2 size={12} />}
                    onClick={handleContentSelect}
                    disabled={isOptimizing}
                  />
                </Tooltip>
              </div>
            }
            styles={{ body: { padding: 0 } }}
          >
            <TextArea
              ref={contentTextAreaRef}
              value={mapHeadersToChinese(currentContent)}
              readOnly
              rows={10}
              className="border-0 rounded-none font-mono text-sm"
              style={{
                resize: "none",
                background: "#fafafa",
                minHeight: 200,
              }}
              onSelect={handleContentSelect}
              onClick={handleContentSelect}
              onKeyUp={handleContentSelect}
            />
          </Card>
          <Card title={t("systemPrompt.optimize.optimized")}>
            {isOptimizing ? (
              <div className="flex flex-col items-center justify-center py-8 gap-3 min-h-[200px]">
                <Spin size="medium" />
                <span className="text-gray-500 text-sm">
                  {t("systemPrompt.optimize.generating")}
                </span>
              </div>
            ) : (
              <Paragraph
                style={{ whiteSpace: "pre-wrap", minHeight: 200, marginBottom: 0 }}
                className="font-mono text-sm"
              >
                {optimizedContent || t("systemPrompt.optimize.empty")}
              </Paragraph>
            )}
          </Card>
        </div>
      </div>
    </Modal>
  );
}

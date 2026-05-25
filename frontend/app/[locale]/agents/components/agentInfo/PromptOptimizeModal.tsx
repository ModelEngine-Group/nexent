import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Alert,
  App,
  Button,
  Card,
  Input,
  InputNumber,
  Modal,
  Segmented,
  Space,
  Tabs,
  Typography,
} from "antd";

import log from "@/lib/logger";
import {
  optimizePromptSection,
  optimizePromptWithBadCase,
  optimizePromptWithFeedback,
} from "@/services/promptService";
import type {
  BadCase,
  OptimizeMode,
  OptimizePromptBadCaseParams,
  OptimizePromptSectionParams,
  OptimizePromptSectionResponse,
} from "@/types/agentConfig";

const { TextArea } = Input;
const { Paragraph, Text } = Typography;

const BAD_CASE_MAX_LIMIT = 10;

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

// ============================================================
// Sub-component: single bad case input card
// ============================================================
interface BadCaseItemProps {
  index: number;
  caseData: BadCase;
  onChange: (updated: BadCase) => void;
  onRemove: () => void;
  disabled?: boolean;
}

function BadCaseItem({ index, caseData, onChange, onRemove, disabled }: BadCaseItemProps) {
  const { t } = useTranslation("common");

  const fields: Array<{
    key: keyof BadCase;
    labelKey: string;
    placeholderKey: string;
    rows: number;
  }> = [
    {
      key: "question",
      labelKey: "systemPrompt.optimize.badCaseQuestion",
      placeholderKey: "systemPrompt.optimize.badCaseQuestionPlaceholder",
      rows: 2,
    },
    {
      key: "label",
      labelKey: "systemPrompt.optimize.badCaseLabel",
      placeholderKey: "systemPrompt.optimize.badCaseLabelPlaceholder",
      rows: 2,
    },
    {
      key: "answer",
      labelKey: "systemPrompt.optimize.badCaseAnswer",
      placeholderKey: "systemPrompt.optimize.badCaseAnswerPlaceholder",
      rows: 2,
    },
    {
      key: "reason",
      labelKey: "systemPrompt.optimize.badCaseReason",
      placeholderKey: "systemPrompt.optimize.badCaseReasonPlaceholder",
      rows: 2,
    },
  ];

  return (
    <Card
      size="small"
      title={t("systemPrompt.optimize.badCaseNum", { index: index + 1 })}
      extra={
        <Button type="text" danger size="small" onClick={onRemove} disabled={disabled}>
          {t("systemPrompt.optimize.badCaseRemove")}
        </Button>
      }
      className="mb-3"
    >
      <div className="flex flex-col gap-3">
        {fields.map(({ key, labelKey, placeholderKey, rows }) => (
          <div key={key}>
            <Text type="secondary" className="text-xs">
              {t(labelKey)}
            </Text>
            <TextArea
              value={caseData[key]}
              onChange={(e) => onChange({ ...caseData, [key]: e.target.value })}
              placeholder={t(placeholderKey)}
              rows={rows}
              className="mt-1"
              disabled={disabled}
            />
          </div>
        ))}
      </div>
    </Card>
  );
}

// ============================================================
// Main Modal component
// ============================================================
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

  // ---- Feedback tab state ----
  const [mode, setMode] = useState<OptimizeMode>("general");
  const [feedback, setFeedback] = useState("");
  const [startPos, setStartPos] = useState<number | null>(null);
  const [endPos, setEndPos] = useState<number | null>(null);

  // ---- Bad Case tab state ----
  const [badCases, setBadCases] = useState<BadCase[]>([]);

  // ---- Shared state ----
  const [activeTab, setActiveTab] = useState<"feedback" | "badCase">("feedback");
  const [optimizedContent, setOptimizedContent] = useState("");
  const [isOptimizing, setIsOptimizing] = useState(false);

  useEffect(() => {
    if (!open) {
      setActiveTab("feedback");
      setFeedback("");
      setOptimizedContent("");
      setIsOptimizing(false);
      setMode("general");
      setStartPos(null);
      setEndPos(null);
      setBadCases([]);
      return;
    }
    setFeedback("");
    setOptimizedContent("");
    setIsOptimizing(false);
    setMode("general");
    setStartPos(null);
    setEndPos(null);
    setBadCases([]);
  }, [open, sectionType, currentContent]);

  // ---- Bad Case handlers ----
  const handleAddBadCase = () => {
    if (badCases.length >= BAD_CASE_MAX_LIMIT) {
      message.warning(t("systemPrompt.optimize.badCaseMax", { max: BAD_CASE_MAX_LIMIT }));
      return;
    }
    setBadCases([...badCases, { question: "", label: "", answer: "", reason: "" }]);
  };

  const handleRemoveBadCase = (index: number) => {
    setBadCases(badCases.filter((_, i) => i !== index));
  };

  const handleUpdateBadCase = (index: number, updated: BadCase) => {
    const next = [...badCases];
    next[index] = updated;
    setBadCases(next);
  };

  // ---- Optimization handler ----
  const handleOptimize = async () => {
    if (activeTab === "feedback") {
      await handleFeedbackOptimize();
    } else {
      await handleBadCaseOptimize();
    }
  };

  const handleFeedbackOptimize = async () => {
    if (mode === "select") {
      if (startPos === null || endPos === null) {
        message.error(t("systemPrompt.optimize.positionRequired"));
        return;
      }
      if (startPos >= endPos) {
        message.error(t("systemPrompt.optimize.invalidPosition"));
        return;
      }
    }

    if (!feedback.trim() && mode !== "select") {
      message.error(t("systemPrompt.optimize.feedbackRequired"));
      return;
    }

    setIsOptimizing(true);
    try {
      const params: OptimizePromptSectionParams = {
        agent_id: agentId,
        task_description: taskDescription,
        model_id: modelId,
        section_type: sectionType,
        section_title: title,
        current_content: currentContent,
        feedback,
        tool_ids: toolIds,
        sub_agent_ids: subAgentIds,
        knowledge_base_display_names: knowledgeBaseDisplayNames,
        mode,
        start_pos: mode === "select" ? startPos ?? undefined : undefined,
        end_pos: mode === "select" ? endPos ?? undefined : undefined,
      };

      let result: OptimizePromptSectionResponse;
      if (mode === "general") {
        result = await optimizePromptSection(params);
      } else {
        result = await optimizePromptWithFeedback(params);
      }
      setOptimizedContent(result.optimized_content || "");
    } catch (error: any) {
      log.error("Optimize prompt section failed:", error);
      message.error(error?.message || t("systemPrompt.optimize.error"));
    } finally {
      setIsOptimizing(false);
    }
  };

  const handleBadCaseOptimize = async () => {
    const filled = badCases.filter(
      (bc) => bc.question.trim() && bc.label.trim() && bc.answer.trim() && bc.reason.trim()
    );
    if (filled.length === 0) {
      message.error(t("systemPrompt.optimize.badCaseRequired"));
      return;
    }

    setIsOptimizing(true);
    try {
      const params: OptimizePromptBadCaseParams = {
        agent_id: agentId,
        task_description: taskDescription,
        model_id: modelId,
        section_type: sectionType,
        section_title: title,
        current_content: currentContent,
        feedback,
        tool_ids: toolIds,
        sub_agent_ids: subAgentIds,
        knowledge_base_display_names: knowledgeBaseDisplayNames,
        bad_cases: filled,
      };
      const result = await optimizePromptWithBadCase(params);
      setOptimizedContent(result.optimized_content || "");
    } catch (error: any) {
      log.error("Optimize with bad cases failed:", error);
      message.error(error?.message || t("systemPrompt.optimize.error"));
    } finally {
      setIsOptimizing(false);
    }
  };

  const handleReplace = () => {
    if (!optimizedContent.trim()) return;
    onReplace(optimizedContent);
  };

  const modeOptions = [
    { value: "general", label: t("systemPrompt.optimize.modeGeneral") },
    { value: "insert", label: t("systemPrompt.optimize.modeInsert") },
    { value: "select", label: t("systemPrompt.optimize.modeSelect") },
  ];

  const tabItems = [
    {
      key: "feedback",
      label: t("systemPrompt.optimize.feedbackTab"),
      children: (
        <div className="flex flex-col gap-4">
          <div>
            <Text strong>{t("systemPrompt.optimize.mode")}</Text>
            <div className="mt-2">
              <Segmented
                value={mode}
                onChange={(v) => setMode(v as OptimizeMode)}
                options={modeOptions}
                block
              />
            </div>
            {mode === "insert" && (
              <Alert
                type="info"
                showIcon
                message={t("systemPrompt.optimize.insertHint")}
                className="mt-2"
              />
            )}
            {mode === "select" && (
              <Alert
                type="info"
                showIcon
                message={t("systemPrompt.optimize.selectHint")}
                className="mt-2"
              />
            )}
          </div>

          {mode === "select" && (
            <div className="flex gap-4">
              <div className="flex-1">
                <Text strong>{t("systemPrompt.optimize.startPos")}</Text>
                <InputNumber
                  value={startPos ?? undefined}
                  onChange={(v) => setStartPos(v)}
                  min={0}
                  max={currentContent.length}
                  className="mt-1 w-full"
                  placeholder="0"
                  disabled={isOptimizing}
                />
                <div className="mt-1 text-xs text-gray-400">
                  {t("systemPrompt.optimize.charCount", { count: currentContent.length })}
                </div>
              </div>
              <div className="flex-1">
                <Text strong>{t("systemPrompt.optimize.endPos")}</Text>
                <InputNumber
                  value={endPos ?? undefined}
                  onChange={(v) => setEndPos(v)}
                  min={0}
                  max={currentContent.length}
                  className="mt-1 w-full"
                  placeholder={String(currentContent.length)}
                  disabled={isOptimizing}
                />
              </div>
            </div>
          )}

          <div>
            <Text strong>
              {mode === "insert"
                ? t("systemPrompt.optimize.insertContent")
                : t("systemPrompt.optimize.feedbackLabel")}
            </Text>
            <TextArea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder={
                mode === "insert"
                  ? t("systemPrompt.optimize.insertPlaceholder")
                  : t("systemPrompt.optimize.feedbackPlaceholder")
              }
              rows={4}
              className="mt-2"
              disabled={isOptimizing}
            />
          </div>
        </div>
      ),
    },
    {
      key: "badCase",
      label: (
        <span>
          {t("systemPrompt.optimize.badCaseTab")}
          {badCases.length > 0 && (
            <span className="ml-1.5 rounded-full bg-blue-500 px-1.5 py-0.5 text-xs text-white">
              {badCases.length}
            </span>
          )}
        </span>
      ),
      children: (
        <div className="flex flex-col gap-4">
          <Alert
            type="info"
            showIcon
            message={t("systemPrompt.optimize.badCaseTabHint")}
          />

          {badCases.length > 0 && (
            <div>
              {badCases.map((bc, i) => (
                <BadCaseItem
                  key={i}
                  index={i}
                  caseData={bc}
                  onChange={(updated) => handleUpdateBadCase(i, updated)}
                  onRemove={() => handleRemoveBadCase(i)}
                  disabled={isOptimizing}
                />
              ))}
            </div>
          )}

          {badCases.length < BAD_CASE_MAX_LIMIT && (
            <Button
              onClick={handleAddBadCase}
              disabled={isOptimizing}
            >
              + {t("systemPrompt.optimize.badCaseAdd")}
            </Button>
          )}
        </div>
      ),
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
        <Tabs
          activeKey={activeTab}
          onChange={(key) => setActiveTab(key as "feedback" | "badCase")}
          items={tabItems}
        />

        <div className="flex justify-end">
          <Button type="primary" onClick={handleOptimize} loading={isOptimizing}>
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

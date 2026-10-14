"use client";

import { Button, Form, Input, Tooltip } from "antd";
import { Plus, Trash2 } from "lucide-react";

import { useTranslation } from "react-i18next";
import { useAgentStore } from "@/stores/agentStore";
import { useAgentReadOnly } from "@/hooks/agent/useAgentReadOnly";
import { StandardInput } from "@/components/common/StandardInput";
import HighFidelityTextArea from "./HighFidelityTextArea";

const MAX_EXAMPLE_QUESTIONS = 6;
const HIGH_FIDELITY_MAX_EXAMPLE_QUESTIONS = 5;

interface AgentConversationGuideProps {
  highFidelity?: boolean;
}

export default function AgentConversationGuide({
  highFidelity = false,
}: AgentConversationGuideProps) {
  const { t } = useTranslation("common");
  const editedAgent = useAgentStore((state) => state.editedAgent!);
  const updateAgentConfig = useAgentStore((state) => state.updateAgentConfig);
  const isReadOnly = useAgentReadOnly();
  const exampleQuestions = editedAgent.example_questions || [];
  const maxQuestions = highFidelity
    ? HIGH_FIDELITY_MAX_EXAMPLE_QUESTIONS
    : MAX_EXAMPLE_QUESTIONS;
  const cannotAddQuestion =
    isReadOnly || exampleQuestions.length >= maxQuestions;

  const addQuestion = () => {
    if (cannotAddQuestion) return;
    updateAgentConfig({
      example_questions: [...exampleQuestions, ""],
    });
  };
  const QuestionInput = highFidelity ? StandardInput : Input;

  const renderQuestion = (question: string, index: number) => (
    <div
      key={index}
      className={
        highFidelity
          ? "flex w-full items-center gap-2"
          : "flex items-center gap-2"
      }
    >
      <QuestionInput
        className={highFidelity ? "!h-8 !w-[564px] !max-w-full" : undefined}
        value={question}
        aria-label={t("agent.guide.example.placeholder")}
        placeholder={t("agent.guide.example.placeholder")}
        disabled={isReadOnly}
        onChange={(event) => {
          const questions = [...exampleQuestions];
          questions[index] = event.target.value;
          updateAgentConfig({ example_questions: questions });
        }}
      />
      <Button
        type="text"
        danger
        disabled={isReadOnly}
        aria-label={t("agent.guide.example.removeAria")}
        icon={<Trash2 size={16} />}
        onClick={() =>
          updateAgentConfig({
            example_questions: exampleQuestions.filter(
              (_, questionIndex) => questionIndex !== index
            ),
          })
        }
      />
    </div>
  );

  return (
    <div className={highFidelity ? "flex flex-col gap-4" : "space-y-4"}>
      <Form.Item
        label={t(
          highFidelity
            ? "agent.highFidelity.greeting"
            : "agent.guide.opening.label"
        )}
        className={highFidelity ? "!mb-0" : "mb-0"}
      >
        {highFidelity ? (
          <HighFidelityTextArea
            limit={200}
            value={editedAgent.greeting_message || ""}
            aria-label={t("agent.guide.opening.label")}
            disabled={isReadOnly}
            onChange={(event) =>
              updateAgentConfig({ greeting_message: event.target.value })
            }
            placeholder={t("agent.highFidelity.greetingPlaceholder")}
            classNames={{
              root: "!h-16 !rounded-[4px] !border-[#c9c9c9]",
              textarea:
                "!h-[62px] !min-h-[62px] !resize-none !rounded-[4px] !px-3 !py-[5px] !text-sm !leading-[22px] !tracking-[0px] !text-[#191919] [font-family:'HarmonyOS_Sans_SC',sans-serif]",
              count:
                "!bottom-2 !right-3 !text-xs !leading-[22px] !text-[#808080]",
            }}
          />
        ) : (
          <Input.TextArea
            value={editedAgent.greeting_message || ""}
            aria-label={t("agent.guide.opening.label")}
            disabled={isReadOnly}
            onChange={(event) =>
              updateAgentConfig({ greeting_message: event.target.value })
            }
            placeholder={t("agent.guide.opening.placeholder")}
            autoSize={{ minRows: 3, maxRows: 6 }}
          />
        )}
      </Form.Item>
      <div className={highFidelity ? "flex flex-col gap-2" : "space-y-4"}>
        <div
          className={
            highFidelity
              ? "flex h-[22px] items-center justify-between"
              : "mb-2 flex items-center justify-between"
          }
        >
          <div className="flex items-center gap-1">
            <span
              className={
                highFidelity
                  ? "text-sm font-normal leading-[22px] tracking-[0px] text-[#191919]"
                  : "text-sm font-medium text-gray-700"
              }
            >
              {t(
                highFidelity
                  ? "agent.highFidelity.presetQuestions"
                  : "agent.greeting.questionsTitle"
              )}
            </span>
            <Tooltip
              title={t("agent.validation.exampleQuestionsMax", {
                max: maxQuestions,
              })}
            >
              <span
                className={
                  highFidelity
                    ? "cursor-help text-sm leading-[22px] text-[#191919]"
                    : "text-xs text-gray-400 cursor-help"
                }
              >
                ({exampleQuestions.length}/{maxQuestions})
              </span>
            </Tooltip>
          </div>
          {!highFidelity && (
            <Tooltip
              title={
                exampleQuestions.length >= maxQuestions
                  ? t("agent.validation.exampleQuestionsMax", {
                      max: maxQuestions,
                    })
                  : undefined
              }
            >
              <span>
                <Button
                  size="middle"
                  icon={<Plus size={14} />}
                  disabled={cannotAddQuestion}
                  onClick={addQuestion}
                >
                  {t("agent.greeting.addQuestion")}
                </Button>
              </span>
            </Tooltip>
          )}
        </div>
        {exampleQuestions.length > 0 && (
          <div className="space-y-2">
            {exampleQuestions.map(renderQuestion)}
          </div>
        )}
        {highFidelity && (
          <>
            <Tooltip
              title={
                exampleQuestions.length >= maxQuestions
                  ? t("agent.validation.exampleQuestionsMax", {
                      max: maxQuestions,
                    })
                  : undefined
              }
            >
              <span className="flex h-[22px] w-fit">
                <Button
                  type="link"
                  autoInsertSpace={false}
                  className="!h-[22px] !p-0 !text-sm !font-normal !leading-[22px] !tracking-[0px] !text-[#2673e5] disabled:!text-[#dfdfdf]"
                  icon={<Plus size={14} />}
                  disabled={cannotAddQuestion}
                  onClick={addQuestion}
                >
                  {t("agent.highFidelity.addPresetQuestion")}
                </Button>
              </span>
            </Tooltip>
          </>
        )}
      </div>
    </div>
  );
}

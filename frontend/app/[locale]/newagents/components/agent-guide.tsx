"use client";

import { Button, Form, Input, Tooltip } from "antd";
import { Plus, Trash2 } from "lucide-react";

import { useTranslation } from "react-i18next";
import { useAgentStore } from "@/stores/agentStore";

const MAX_EXAMPLE_QUESTIONS = 6;

export default function AgentConversationGuide() {
  const { t } = useTranslation("common");
  const editedAgent = useAgentStore((state) => state.editedAgent!);
  const updateAgentConfig = useAgentStore(
    (state) => state.updateAgentConfig
  );
  const exampleQuestions = editedAgent.example_questions || [];

  return (
    <div className="space-y-4">
      <Form.Item label={t("agent.guide.opening.label")} className="mb-0">
        <Input.TextArea
          value={editedAgent.greeting_message || ""}
          onChange={(event) =>
            updateAgentConfig({ greeting_message: event.target.value })
          }
          placeholder={t("agent.guide.opening.placeholder")}
          autoSize={{ minRows: 3, maxRows: 6 }}
        />
      </Form.Item>
      <div>
        <div className="mb-2 flex items-center justify-between">
          <div className="flex items-center gap-1">
            <span className="text-sm font-medium text-gray-700">
              {t("agent.greeting.questionsTitle")}
            </span>
            <Tooltip title={t("agent.validation.exampleQuestionsMax", { max: MAX_EXAMPLE_QUESTIONS })}>
              <span className="text-xs text-gray-400 cursor-help">
                ({exampleQuestions.length}/{MAX_EXAMPLE_QUESTIONS})
              </span>
            </Tooltip>
          </div>
          <Tooltip
            title={
              exampleQuestions.length >= MAX_EXAMPLE_QUESTIONS
                ? t("agent.validation.exampleQuestionsMax", { max: MAX_EXAMPLE_QUESTIONS })
                : undefined
            }
          >
            <span>
              <Button
                size="middle"
                icon={<Plus size={14} />}
                disabled={exampleQuestions.length >= MAX_EXAMPLE_QUESTIONS}
                onClick={() =>
                  updateAgentConfig({
                    example_questions: [...exampleQuestions, ""],
                  })
                }
              >
                {t("agent.greeting.addQuestion")}
              </Button>
            </span>
          </Tooltip>
        </div>
        <div className="space-y-2">
          {exampleQuestions.map((question, index) => (
            <div key={index} className="flex items-center gap-2">
              <Input
                value={question}
                placeholder={t("agent.guide.example.placeholder")}
                onChange={(event) => {
                  const questions = [...exampleQuestions];
                  questions[index] = event.target.value;
                  updateAgentConfig({ example_questions: questions });
                }}
              />
              <Button
                type="text"
                danger
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
          ))}
        </div>
      </div>
    </div>
  );
}

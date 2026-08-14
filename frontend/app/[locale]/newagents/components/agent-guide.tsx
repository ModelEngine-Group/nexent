"use client";

import { Button, Form, Input } from "antd";
import { Plus, Trash2 } from "lucide-react";

import { useAgentStore } from "@/stores/agentStore";

const MAX_EXAMPLE_QUESTIONS = 6;

export default function AgentConversationGuide() {
  const editedAgent = useAgentStore((state) => state.editedAgent!);
  const updateAgentConfig = useAgentStore(
    (state) => state.updateAgentConfig
  );
  const exampleQuestions = editedAgent.example_questions || [];

  return (
    <div className="space-y-4">
      <Form.Item label="开场白" className="mb-0">
        <Input.TextArea
          value={editedAgent.greeting_message || ""}
          onChange={(event) =>
            updateAgentConfig({ greeting_message: event.target.value })
          }
          placeholder="请输入用户首次进入会话时看到的开场白"
          autoSize={{ minRows: 3, maxRows: 6 }}
        />
      </Form.Item>
      <div>
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-medium text-gray-700">示例问题</span>
          <Button
            type="dashed"
            size="small"
            icon={<Plus size={14} />}
            disabled={exampleQuestions.length >= MAX_EXAMPLE_QUESTIONS}
            onClick={() =>
              updateAgentConfig({
                example_questions: [...exampleQuestions, ""],
              })
            }
          >
            添加问题
          </Button>
        </div>
        <div className="space-y-2">
          {exampleQuestions.map((question, index) => (
            <div key={index} className="flex items-center gap-2">
              <Input
                value={question}
                placeholder="请输入示例问题"
                onChange={(event) => {
                  const questions = [...exampleQuestions];
                  questions[index] = event.target.value;
                  updateAgentConfig({ example_questions: questions });
                }}
              />
              <Button
                type="text"
                danger
                aria-label="删除示例问题"
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

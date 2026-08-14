"use client";

import { useTranslation } from "react-i18next";
import { Form, Input, Row, Col, Flex, Avatar } from "antd";
import { Upload } from "lucide-react";

import { useAgentStore } from "@/stores/agentStore";

export default function AgentInfo() {
  const { t } = useTranslation("common");
  const editedAgent = useAgentStore((state) => state.editedAgent!);
  const updateDraft = useAgentStore((state) => state.updateDraft);

  return (
    <div className="w-full">
      <Row gutter={[16, 0]}>
        {/* Left: text fields */}
        <Col xs={24} md={18}>
          <Row gutter={[12, 0]}>
            <Col xs={24} sm={12}>
              <Form.Item label={t("agent.field.displayName")} className="mb-3">
                <Input
                  placeholder={t("agent.field.displayNamePlaceholder")}
                  value={editedAgent.display_name}
                  onChange={(event) =>
                    updateDraft({ display_name: event.target.value })
                  }
                />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12}>
              <Form.Item label={t("agent.field.name")} className="mb-3">
                <Input
                  placeholder={t("agent.field.namePlaceholder")}
                  value={editedAgent.name}
                  onChange={(event) =>
                    updateDraft({ name: event.target.value })
                  }
                />
              </Form.Item>
            </Col>
          </Row>

          <Row gutter={[12, 0]}>
            <Col xs={24} sm={12}>
              <Form.Item label={t("agent.field.author")} className="mb-3">
                <Input
                  placeholder={t("agent.field.authorPlaceholder")}
                  value={editedAgent.author}
                  onChange={(event) =>
                    updateDraft({ author: event.target.value })
                  }
                />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item label={t("agent.field.description")} className="mb-0">
            <Input.TextArea
              placeholder={t("agent.field.descriptionPlaceholder")}
              rows={3}
              value={editedAgent.description}
              onChange={(event) =>
                updateDraft({ description: event.target.value })
              }
            />
          </Form.Item>
        </Col>

        {/* Right: icon upload */}
        <Col xs={24} md={6}>
          <Flex vertical align="center" className="h-full">
            <div className="mb-2 text-xs text-gray-500 font-medium">
              {t("agent.field.icon")}
            </div>
            <div className="relative group cursor-pointer">
              <Avatar
                size={72}
                src={editedAgent.icon_url}
                className="border-2 border-dashed border-gray-300"
              >
                {editedAgent.display_name?.[0] ?? "A"}
              </Avatar>
              <div className="absolute inset-0 flex items-center justify-center rounded-full bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity">
                <Upload size={18} className="text-white" />
              </div>
            </div>
            <div className="mt-2 text-xs text-gray-400 text-center">
              {t("agent.field.iconHint")}
            </div>
          </Flex>
        </Col>
      </Row>
    </div>
  );
}

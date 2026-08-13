"use client";

import { useTranslation } from "react-i18next";
import { Form, Select, Switch, Row, Col, Flex } from "antd";
import { Globe } from "lucide-react";

import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { useGroupList } from "@/hooks/group/useGroupList";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";

export default function AgentDeployment() {
  const { t } = useTranslation("common");
  const { user } = useAuthorizationContext();
  const editedAgent = useAgentConfigStore((state) => state.editedAgent);
  const updateAgent = useAgentConfigStore((state) => state.updateAgentConfig);
  const { data: groupData } = useGroupList(user?.tenantId ?? null);
  const allGroups = groupData?.groups ?? [];

  const groupOptions = allGroups.map((g: any) => ({
    value: g.id,
    label: g.name,
  }));

  const permissionOptions = [
    { value: "READ_ONLY", label: t("agent.permission.readOnly") },
    { value: "EDITABLE", label: t("agent.permission.editable") },
    { value: "INHERIT", label: t("agent.permission.inherit") },
  ];

  return (
    <div className="w-full">
      <Row gutter={[16, 0]}>
        {/* User Groups */}
        <Col xs={24} sm={12}>
          <Form.Item
            label={t("agent.field.groupIds")}
            className="mb-3"
          >
            <Select
              mode="multiple"
              placeholder={t("agent.field.groupIdsPlaceholder")}
              options={groupOptions}
              value={editedAgent.group_ids ?? []}
              onChange={(vals) => updateAgent({ group_ids: vals })}
              allowClear
            />
          </Form.Item>
        </Col>

        {/* In-group Permission */}
        <Col xs={24} sm={12}>
          <Form.Item
            label={t("agent.field.ingroupPermission")}
            className="mb-3"
          >
            <Select
              placeholder={t("agent.field.ingroupPermissionPlaceholder")}
              options={permissionOptions}
              value={editedAgent.ingroup_permission ?? "READ_ONLY"}
              onChange={(val) => updateAgent({ ingroup_permission: val })}
            />
          </Form.Item>
        </Col>
      </Row>

      <Row gutter={[16, 0]}>
        {/* Is Main Agent */}
        <Col xs={24} sm={12}>
          <Form.Item
            label={t("agent.field.isMainAgent")}
            className="mb-3"
          >
            <Flex align="center" gap={8}>
              <Switch
                checked={editedAgent.is_main_agent ?? false}
                onChange={(checked) => updateAgent({ is_main_agent: checked })}
              />
              <span className="text-xs text-gray-500">
                {editedAgent.is_main_agent
                  ? t("agent.mainAgent.enabled")
                  : t("agent.mainAgent.disabled")}
              </span>
            </Flex>
          </Form.Item>
        </Col>

        {/* A2A Enabled */}
        <Col xs={24} sm={12}>
          <Form.Item
            label={t("agent.field.a2aEnabled")}
            className="mb-3"
          >
            <Flex align="center" gap={8}>
              <Switch
                checked={editedAgent.enable_a2a ?? false}
                onChange={(checked) => updateAgent({ enable_a2a: checked })}
              />
              <Flex align="center" gap={4}>
                <Globe size={12} className="text-gray-400" />
                <span className="text-xs text-gray-500">
                  {editedAgent.enable_a2a
                    ? t("agent.a2a.publishAsA2AAgent")
                    : t("agent.a2a.notPublished")}
                </span>
              </Flex>
            </Flex>
          </Form.Item>
        </Col>
      </Row>
    </div>
  );
}

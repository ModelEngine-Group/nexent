"use client";

import { useTranslation } from "react-i18next";
import { Form, Select, Switch, Row, Col, Flex } from "antd";
import { Globe } from "lucide-react";

import { useAgentStore } from "@/stores/agentStore";
import { useGroupList } from "@/hooks/group/useGroupList";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";

export default function AgentDeployment() {
  const { t } = useTranslation("common");
  const { user } = useAuthorizationContext();
  const editedAgent = useAgentStore((state) => state.editedAgent!);
  const updateAgent = useAgentStore((state) => state.updateAgentConfig);
  const { data: groupData } = useGroupList(user?.tenantId ?? null);
  const allGroups = groupData?.groups ?? [];

  const groupOptions = allGroups.map((group) => ({
    value: group.group_id,
    label: group.group_name,
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
            label={t("agent.deployment.groupIds")}
            className="mb-3"
          >
            <Select
              mode="multiple"
              showSearch={{ optionFilterProp: "label" }}
              placeholder={t("agent.deployment.groupIdsPlaceholder")}
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
            label={t("agent.deployment.ingroupPermission")}
            className="mb-3"
          >
            <Select
              placeholder={t("agent.deployment.ingroupPermissionPlaceholder")}
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
            label={t("agent.isMainAgent")}
            className="mb-3"
            tooltip={t("agent.deployment.isMainAgentTooltip")}
          >
            <Switch
              checked={editedAgent.is_main_agent ?? false}
              onChange={(checked) => updateAgent({ is_main_agent: checked })}
            />
          </Form.Item>
        </Col>

        {/* A2A Enabled */}
        <Col xs={24} sm={12}>
          <Form.Item
            label={t("agent.deployment.a2aEnabled")}
            className="mb-3"
            tooltip={t("agent.deployment.a2aEnabledTooltip")}
          >
            <Switch
              checked={editedAgent.is_a2a ?? false}
              onChange={(checked) => updateAgent({ is_a2a: checked })}
            />
          </Form.Item>
        </Col>
      </Row>
    </div>
  );
}

// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useTranslation } from "react-i18next";
import { Checkbox, Form, Switch, Row, Col } from "antd";
import { GroupPermissionSelect } from "@/components/permission/GroupPermissionSelect";
import { getGroupPermissions } from "@/lib/groupPermission";
import { AgentSettingHint } from "./agent-setting-hint";

import { useAgentStore } from "@/stores/agentStore";
import { useGroupList } from "@/hooks/group/useGroupList";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useAgentReadOnly } from "@/hooks/agent/useAgentReadOnly";

interface AgentDeploymentProps {
  highFidelity?: boolean;
}

export function AgentDeploymentOptions({
  highFidelity = false,
}: AgentDeploymentProps = {}) {
  const { t } = useTranslation("common");
  const editedAgent = useAgentStore((state) => state.editedAgent!);
  const updateAgent = useAgentStore((state) => state.updateAgentConfig);
  const isReadOnly = useAgentReadOnly();

  return (
    <>
      <AgentSettingHint
        label={t(
          highFidelity ? "agent.highFidelity.mainAgent" : "agent.isMainAgent"
        )}
        hint={t("agent.deployment.isMainAgentTooltip")}
      >
        <Checkbox
          checked={editedAgent.is_main_agent ?? false}
          disabled={isReadOnly}
          onChange={(event) =>
            updateAgent({ is_main_agent: event.target.checked })
          }
        >
          {t(
            highFidelity ? "agent.highFidelity.mainAgent" : "agent.isMainAgent"
          )}
        </Checkbox>
      </AgentSettingHint>
      <AgentSettingHint
        label={t(
          highFidelity
            ? "agent.highFidelity.a2a"
            : "agent.deployment.a2aEnabled"
        )}
        hint={t("agent.deployment.a2aEnabledTooltip")}
      >
        <Checkbox
          checked={editedAgent.is_a2a ?? false}
          disabled={isReadOnly}
          onChange={(event) => updateAgent({ is_a2a: event.target.checked })}
        >
          {t(
            highFidelity
              ? "agent.highFidelity.a2a"
              : "agent.deployment.a2aEnabled"
          )}
        </Checkbox>
      </AgentSettingHint>
    </>
  );
}

export default function AgentDeployment({
  highFidelity = false,
}: AgentDeploymentProps = {}) {
  const { t } = useTranslation("common");
  const { user } = useAuthorizationContext();
  const editedAgent = useAgentStore((state) => state.editedAgent!);
  const updateAgent = useAgentStore((state) => state.updateAgentConfig);
  const isReadOnly = useAgentReadOnly();
  const { data: groupData, isLoading } = useGroupList(user?.tenantId ?? null);
  const rules = getGroupPermissions(editedAgent);
  const groups = groupData?.groups ?? [];
  const groupNames = new Map(
    groups.map((group) => [group.group_id, group.group_name])
  );
  const options = groups.map((group) => ({
    value: group.group_id,
    label: group.group_name,
  }));
  for (const rule of rules) {
    if (!groupNames.has(rule.group_id)) {
      options.push({
        value: rule.group_id,
        label: `${t("group.deleted")} #${rule.group_id}`,
      });
    }
  }
  const canManageSharing =
    !editedAgent.created_by ||
    editedAgent.created_by === user?.id ||
    ["SU", "ADMIN", "SPEED", "ASSET_OWNER"].includes(user?.role ?? "");
  const groupSharing = (
    <Form.Item label={t("agentConfig.layout.agentPermission")}>
      <GroupPermissionSelect
        value={rules}
        options={options}
        disabled={isReadOnly || isLoading || !canManageSharing}
        onChange={(group_permissions) => updateAgent({ group_permissions })}
      />
    </Form.Item>
  );

  if (highFidelity) {
    return <div className="w-[406px] max-w-full">{groupSharing}</div>;
  }

  return (
    <div className="w-full">
      {groupSharing}
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

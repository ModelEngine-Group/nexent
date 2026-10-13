"use client";

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Checkbox, Form, Radio, Select, Switch, Row, Col, Tooltip } from "antd";

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
      <Tooltip title={t("agent.deployment.isMainAgentTooltip")}>
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
      </Tooltip>
      <Tooltip title={t("agent.deployment.a2aEnabledTooltip")}>
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
      </Tooltip>
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
  const currentAgentId = useAgentStore((state) => state.agentId);
  const serverSnapshotRevision = useAgentStore(
    (state) => state.serverSnapshotRevision
  );
  const isReadOnly = useAgentReadOnly();
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

  const initialScope =
    (editedAgent.group_ids ?? []).length === 0
      ? "PRIVATE"
      : (editedAgent.ingroup_permission ?? "READ_ONLY");
  const [permissionView, setPermissionView] = useState({
    agentId: currentAgentId,
    revision: serverSnapshotRevision,
    scope: initialScope,
  });
  if (
    permissionView.agentId !== currentAgentId ||
    permissionView.revision !== serverSnapshotRevision
  ) {
    setPermissionView({
      agentId: currentAgentId,
      revision: serverSnapshotRevision,
      scope: initialScope,
    });
  }

  if (highFidelity) {
    const scope =
      permissionView.agentId === currentAgentId &&
      permissionView.revision === serverSnapshotRevision
        ? permissionView.scope
        : initialScope;
    const canonicalScopes = ["PRIVATE", "READ_ONLY", "EDIT"];

    return (
      <div className="flex w-[406px] max-w-full flex-col gap-2">
        <span
          id="agent-permission-label"
          className="text-sm font-normal leading-[22px] tracking-[0px] text-[#191919]"
        >
          {t("agentConfig.layout.agentPermission")}
        </span>
        <Radio.Group
          aria-labelledby="agent-permission-label"
          value={scope}
          disabled={isReadOnly}
          onChange={(event) => {
            const value = event.target.value as
              "PRIVATE" | "READ_ONLY" | "EDIT";
            setPermissionView({
              agentId: currentAgentId,
              revision: serverSnapshotRevision,
              scope: value,
            });
            updateAgent({
              ingroup_permission: value,
              ...(value === "PRIVATE" ? { group_ids: [] } : {}),
            });
          }}
          className="flex flex-wrap gap-4 text-sm leading-[22px] tracking-[0px] text-[#191919]"
        >
          <Radio value="PRIVATE">
            {t("agentConfig.layout.permissionPrivate")}
          </Radio>
          <Radio value="READ_ONLY">
            {t("agentConfig.layout.permissionReadable")}
          </Radio>
          <Radio value="EDIT">
            {t("agentConfig.layout.permissionEditable")}
          </Radio>
          {!canonicalScopes.includes(scope) ? (
            <Radio value={scope} disabled>
              {scope}
            </Radio>
          ) : null}
        </Radio.Group>
        {scope !== "PRIVATE" ? (
          <Form.Item label={t("agent.deployment.groupIds")} className="!mb-0">
            <Select
              mode="multiple"
              showSearch={{ optionFilterProp: "label" }}
              placeholder={t("agent.deployment.groupIdsPlaceholder")}
              options={groupOptions}
              value={editedAgent.group_ids ?? []}
              disabled={isReadOnly}
              onChange={(vals) => updateAgent({ group_ids: vals })}
              allowClear
            />
          </Form.Item>
        ) : null}
      </div>
    );
  }

  return (
    <div className="w-full">
      <Row gutter={[16, 0]}>
        {/* User Groups */}
        <Col xs={24} sm={12}>
          <Form.Item label={t("agent.deployment.groupIds")} className="mb-3">
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

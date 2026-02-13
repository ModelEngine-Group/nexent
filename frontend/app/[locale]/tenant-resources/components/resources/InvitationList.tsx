"use client";

import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import dayjs from "dayjs";
import {
  Table,
  Button,
  Modal,
  Form,
  Input,
  Select,
  Popconfirm,
  message,
  Tag,
  Pagination,
  Collapse,
  DatePicker,
  Progress,
} from "antd";
import { ColumnsType } from "antd/es/table";
import { useInvitationList } from "@/hooks/invitation/useInvitationList";
import { useGroupList } from "@/hooks/group/useGroupList";
import { getTenantDefaultGroupId } from "@/services/groupService";
import {
  createInvitation,
  updateInvitation,
  deleteInvitation,
  checkInvitationCodeExists,
  type Invitation,
  type CreateInvitationRequest,
  type UpdateInvitationRequest,
} from "@/services/invitationService";
import { Plus, Edit, Trash2, CheckCircle, Clock, XCircle, Copy, CircleSlash } from "lucide-react";
import { Tooltip } from "@/components/ui/tooltip";
import { formatDate } from "@/lib/date";

const { Panel } = Collapse;

export default function InvitationList({ tenantId }: { tenantId: string | null }) {
  const { t } = useTranslation("common");
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [editingInvitation, setEditingInvitation] = useState<Invitation | null>(null);
  const [modalVisible, setModalVisible] = useState(false);

  const [form] = Form.useForm();

  // Fetch invitations
  const { data, isLoading, refetch } = useInvitationList({
    tenant_id: tenantId || undefined,
    page: currentPage,
    page_size: pageSize,
    sort_by: "update_time",
    sort_order: "desc",
  });

  // Fetch groups for group selection
  const { data: groupData } = useGroupList(tenantId, 1, 100); // Get all groups for selection
  const groups = groupData?.groups || [];

  const invitations = data?.items || [];

  const openCreate = async () => {
    setEditingInvitation(null);
    form.resetFields();

    // Get default group for the tenant
    let defaultGroupIds: number[] = [];
    if (tenantId) {
      try {
        const defaultGroupId = await getTenantDefaultGroupId(tenantId);
        if (defaultGroupId) {
          defaultGroupIds = [defaultGroupId];
        }
      } catch (error) {
        console.warn("Failed to get default group:", error);
        // Show user-friendly message
        message.warning("Unable to load default group. You can manually select groups.");
      }
    } else {
      console.log("No tenantId available for getting default group");
    }
    form.setFieldsValue({
      code_type: "USER_INVITE",
      capacity: 1,
      group_ids: defaultGroupIds,
    });
    setModalVisible(true);
  };

  const openEdit = (invitation: Invitation) => {
    setEditingInvitation(invitation);
    form.setFieldsValue({
      code_type: invitation.code_type,
      capacity: invitation.capacity,
      invitation_code: invitation.invitation_code,
      group_ids: invitation.group_ids || [],
      expiry_date: invitation.expiry_date ? dayjs(invitation.expiry_date) : undefined,
    });
    setModalVisible(true);
  };

  const handleDelete = async (invitationCode: string) => {
    try {
      await deleteInvitation(invitationCode);
      message.success(t("tenantResources.invitationDeleted"));
      refetch();
    } catch (error: any) {
      // Check if it's an authentication error
      if (error.code === 401 || error.code === 499 || error.message?.includes("Login expired")) {
        // Let the global session expired handler deal with it
        throw error;
      } else {
        // For other errors, show specific error message
        const errorMessage = error.response?.data?.message || error.message || "Failed to delete invitation";
        message.error(errorMessage);
      }
    }
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();

      if (!tenantId) {
        message.error("No tenant selected");
        return;
      }

      // Format expiry_date from dayjs to string
      const formattedExpiryDate =
        values.expiry_date && dayjs(values.expiry_date).isValid()
          ? dayjs(values.expiry_date).format("YYYY-MM-DD")
          : undefined;

      if (editingInvitation) {
        // Update invitation
        const updateData: UpdateInvitationRequest = {
          capacity: values.capacity,
          expiry_date: formattedExpiryDate,
          group_ids: values.group_ids || [],
        };
        await updateInvitation(editingInvitation.invitation_code, updateData);
        message.success(t("tenantResources.invitation.invitationUpdated"));
      } else {
        // Create invitation
        const createData: CreateInvitationRequest = {
          tenant_id: tenantId,
          code_type: values.code_type,
          invitation_code: values.invitation_code?.toUpperCase(),
          capacity: values.capacity,
          group_ids: values.group_ids || [],
          expiry_date: formattedExpiryDate,
        };
        await createInvitation(createData);
        message.success(t("tenantResources.invitation.invitationCreated"));
      }
      setModalVisible(false);
      refetch();
    } catch (error: any) {
      // Check if it's an authentication error
      if (error.code === 401 || error.code === 499 || error.message?.includes("Login expired")) {
        // Let the global session expired handler deal with it
        throw error;
      } else {
        // For other errors, show specific error message
        const errorMessage = error.response?.data?.message || error.message || "Operation failed";
        message.error(errorMessage);
      }
    }
  };

  // Create group name mapping
  const groupNameMap = useMemo(() => {
    const map = new Map<number, string>();
    groups.forEach((group) => {
      map.set(group.group_id, group.group_name);
    });
    return map;
  }, [groups]);

  // Get group names for invitation
  const getGroupNames = (groupIds?: number[]) => {
    if (!groupIds || groupIds.length === 0) return [];
    return groupIds.map((id) => groupNameMap.get(id) || `Group ${id}`).filter(Boolean);
  };

  const columns: ColumnsType<Invitation> = useMemo(
    () => [
      {
        title: t("tenantResources.invitation.invitationCode"),
        dataIndex: "invitation_code",
        key: "invitation_code",
        width: 80,
        render: (code: string) => (
          <div className="flex items-center justify-between gap-2">
            <span className="font-mono font-medium">{code}</span>
            <Tooltip title={t("common.copy")}>
              <Button
                type="text"
                icon={<Copy className="h-4 w-4" />}
                onClick={() => {
                  navigator.clipboard.writeText(code);
                  message.success(t("common.copied"));
                }}
                aria-label={t("common.copy")}
              />
            </Tooltip>
          </div>
        ),
      },
      {
        title: t("tenantResources.invitation.codeType"),
        dataIndex: "code_type",
        key: "code_type",
        width: 80,
        render: (type: string) => {
          return <Tag color="default">{t(`tenantResources.invitation.codeType.${type}`)}</Tag>;
        },
      },
      {
        title: t("tenantResources.invitation.usage"),
        key: "usage",
        width: 80,
        render: (_, record: Invitation) => {
          const { capacity, used_times } = record;
          const remaining = capacity - used_times;
          const percent = Math.round((remaining / capacity) * 100);
          return (
            <div className="flex ml-5">
              <Progress
                type="dashboard"
                percent={percent}
                gapDegree={100}
                format={() => t("tenantResources.invitation.remaining", { remaining })}
                size={20}
                strokeColor={remaining > 0 ? "#52c41a" : "#ff4d4f"}
              />
            </div>
          );
        },
      },
      {
        title: t("tenantResources.invitation.expiryDate"),
        dataIndex: "expiry_date",
        key: "expiry_date",
        width: 120,
        render: (date: string) =>
          date ? formatDate(date) : <span className="text-gray-400">{t("tenantResources.invitation.noExpiry")}</span>,
      },
      {
        title: t("tenantResources.invitation.groupNames"),
        dataIndex: "group_ids",
        key: "group_names",
        width: 300,
        render: (groupIds: number[]) => {
          const names = getGroupNames(groupIds);
          return (
            <div className="flex flex-wrap gap-1">
              {names.length > 0 ? (
                names.map((name, index) => (
                  <Tag
                    key={index}
                    color="blue"
                    variant="outlined"
                  >
                    {name}
                  </Tag>
                ))
              ) : (
                <span className="text-gray-400">{t("tenantResources.invitation.noGroups")}</span>
              )}
            </div>
          );
        },
      },
      {
        title: t("tenantResources.invitation.status"),
        dataIndex: "status",
        key: "status",
        width: 120,
        render: (status: string) => {
          const color =
            status === "IN_USE" ? "#229954" :
            status === "EXPIRE" ? "#AEB6BF" :
            status === "RUN_OUT" ? "#E74C3C" : "#2E4053";

          const icon = status === "IN_USE" ? <CheckCircle className="w-3 h-3 mr-1" /> :
                      status === "EXPIRE" ? <Clock className="w-3 h-3 mr-1" /> :
                      status === "RUN_OUT" ? <CircleSlash className="w-3.5 h-3 mr-1" /> :
                      <XCircle className="w-3 h-3 mr-1" />;

          return (
            <Tag
              color={color}
              className="inline-flex items-center"
              variant="solid"
            >
              {icon}
              {t(`tenantResources.invitation.status.${status}`)}
            </Tag>
          );
        },
      },
      {
        title: t("tenantResources.invitation.actions"),
        key: "actions",
        width: 200,
        fixed: "right",
        render: (_, record: Invitation) => (
          <div className="flex items-center space-x-2">
            <Tooltip title={t("tenantResources.invitation.editInvitation")}>
              <Button
                type="text"
                icon={<Edit className="h-4 w-4" />}
                onClick={() => openEdit(record)}
                size="small"
              />
            </Tooltip>
            <Popconfirm
              title={t("tenantResources.invitation.confirmDeleteInvitation", { code: record.invitation_code })}
              description={t("common.cannotBeUndone")}
              onConfirm={() => handleDelete(record.invitation_code)}
              okText={t("common.confirm")}
              cancelText={t("common.cancel")}
            >
              <Tooltip title={t("tenantResources.invitation.deleteInvitation")}>
                <Button
                  type="text"
                  danger
                  icon={<Trash2 className="h-4 w-4" />}
                  size="small"
                />
              </Tooltip>
            </Popconfirm>
          </div>
        ),
      },
    ],
    [groupNameMap]
  );

  // Group invitations by tenant for collapse view
  const groupedInvitations = useMemo(() => {
    if (tenantId) return null; // Don't group when tenant is selected

    const groups: Record<string, Invitation[]> = {};
    invitations.forEach((invitation) => {
      const tenantId = invitation.tenant_id || "unknown";
      if (!groups[tenantId]) {
        groups[tenantId] = [];
      }
      groups[tenantId].push(invitation);
    });
    return groups;
  }, [invitations, tenantId]);

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="mb-4 flex justify-between items-center flex-shrink-0">
        <div />
        <div>
          <Button type="primary" onClick={openCreate} icon={<Plus className="h-4 w-4"/>}>
            {t("tenantResources.invitation.createInvitation")}
          </Button>
        </div>
      </div>

      {tenantId ? (
        // Single tenant view with pagination
        <Table
          columns={columns}
          dataSource={invitations}
          loading={isLoading}
          rowKey="invitation_id"
          pagination={{ pageSize: 10 }}
          scroll={{ x: 1000 }}
          className="flex-1"
        />
      ) : (
        // Multi-tenant view with collapse
        <Collapse>
          {Object.entries(groupedInvitations || {}).map(([tenantId, tenantInvitations]) => (
            <Panel header={`Tenant: ${tenantId}`} key={tenantId}>
              <Table
                columns={columns}
                dataSource={tenantInvitations}
                loading={isLoading}
                rowKey="invitation_id"
                pagination={{ pageSize: 10 }}
                size="small"
                scroll={{ x: 1000 }}
              />
            </Panel>
          ))}
        </Collapse>
      )}

      {/* Create/Edit Modal */}
      <Modal
        title={
          <span>
            {editingInvitation
              ? `${t("tenantResources.invitation.editInvitation")}: ${editingInvitation.invitation_code}`
              : t("tenantResources.invitation.createInvitation")}
          </span>
        }
        open={modalVisible}
        onOk={handleSubmit}
        onCancel={() => setModalVisible(false)}
        okText={t("common.confirm")}
        cancelText={t("common.cancel")}
        width={600}
        maskClosable={false}
      >
        <Form form={form} layout="vertical">
          {!editingInvitation && (
            <Form.Item
              name="code_type"
              label={t("tenantResources.invitation.codeType")}
              rules={[{ required: true, message: t("tenantResources.invitation.codeTypeRequired") }]}
            >
              <Select
                placeholder={t("tenantResources.invitation.codeType")}
                options={[
                  { value: "ADMIN_INVITE", label: t("tenantResources.invitation.codeType.ADMIN_INVITE") },
                  { value: "DEV_INVITE", label: t("tenantResources.invitation.codeType.DEV_INVITE") },
                  { value: "USER_INVITE", label: t("tenantResources.invitation.codeType.USER_INVITE") },
                ]}
              />
            </Form.Item>
          )}

          {!editingInvitation && (
            <Form.Item
              name="invitation_code"
              label={t("tenantResources.invitation.invitationCode")}
              rules={[
                {
                  pattern: /^[A-Z0-9]*$/,
                  message: t("tenantResources.invitation.invitationCodeInvalid")
                },
                {
                  validator: async (_, value) => {
                    if (!value) {
                      return Promise.reject(new Error("Required"));
                    }
                    try {
                      const exists = await checkInvitationCodeExists(value);
                      if (exists) {
                        return Promise.reject(new Error(t("tenantResources.invitation.alreadyExists")));
                      }
                      return Promise.resolve();
                    } catch {
                      return Promise.reject(new Error("Failed to check invitation code"));
                    }
                  },
                }
              ]}
            >
              <Input
                placeholder={t("tenantResources.invitation.invitationCode")}
                onChange={(e) => {
                  const value = e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, "");
                  form.setFieldsValue({ invitation_code: value });
                }}
              />
            </Form.Item>
          )}

          <Form.Item
            name="capacity"
            label={t("tenantResources.invitation.capacity")}
            rules={[
              { required: true, message: t("tenantResources.invitation.capacityRequired") },
              {
                validator: (_, value) => {
                  if (!value) return Promise.resolve();
                  const numValue = Number(value);
                  if (isNaN(numValue) || numValue < 1) {
                    return Promise.reject(new Error(t("tenantResources.invitation.capacityMin")));
                  }
                  return Promise.resolve();
                }
              }
            ]}
          >
            <Input type="number" placeholder={t("tenantResources.invitation.capacity")} min={1} />
          </Form.Item>

          <Form.Item name="group_ids" label={t("tenantResources.invitation.groupNames")}>
            <Select
              mode="multiple"
              placeholder={t("tenantResources.invitation.groupNames")}
              options={groups.map((group) => ({
                label: group.group_name,
                value: group.group_id,
              }))}
            />
          </Form.Item>

          <Form.Item name="expiry_date" label={t("tenantResources.invitation.expiryDate")}>
            <DatePicker
              format="YYYY-MM-DD"
              placeholder={t("tenantResources.invitation.expiryDate")}
              style={{ width: "100%" }}
              disabledDate={(current) => {
                if (!current) return false;
                return current < dayjs().startOf('day');
              }}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

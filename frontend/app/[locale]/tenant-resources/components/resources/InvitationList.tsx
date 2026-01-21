"use client";

import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
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
} from "antd";
import { ColumnsType } from "antd/es/table";
import { useInvitationList } from "@/hooks/invitation/useInvitationList";
import { useGroupList } from "@/hooks/group/useGroupList";
import {
  createInvitation,
  updateInvitation,
  deleteInvitation,
  type Invitation,
  type CreateInvitationRequest,
  type UpdateInvitationRequest,
} from "@/services/invitationService";
import { Plus, Edit, Trash2, CheckCircle, Clock, XCircle, AlertCircle } from "lucide-react";
import { Tooltip } from "@/components/ui/tooltip";
import dayjs from "dayjs";

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
  });

  // Fetch groups for group selection
  const { data: groupData } = useGroupList(tenantId, 1, 100); // Get all groups for selection
  const groups = groupData?.groups || [];

  const invitations = data?.items || [];
  const total = data?.total || 0;

  const openCreate = () => {
    setEditingInvitation(null);
    form.resetFields();
    form.setFieldsValue({
      code_type: "USER_INVITE",
      capacity: 1,
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

      if (editingInvitation) {
        // Update invitation
        const updateData: UpdateInvitationRequest = {
          capacity: values.capacity,
          expiry_date: values.expiry_date ? values.expiry_date.format("YYYY-MM-DD") : undefined,
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
          expiry_date: values.expiry_date ? values.expiry_date.format("YYYY-MM-DD") : undefined,
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
        width: 150,
        render: (code: string) => <span className="font-mono font-medium">{code}</span>,
      },
      {
        title: t("tenantResources.invitation.codeType"),
        dataIndex: "code_type",
        key: "code_type",
        width: 120,
        render: (type: string) => {
          const color =
            type === "ADMIN_INVITE" ? "magenta" :
            type === "DEV_INVITE" ? "blue" : "green";
          return <Tag color={color}>{t(`tenantResources.invitation.codeType.${type}`)}</Tag>;
        },
      },
      {
        title: t("tenantResources.invitation.groupNames"),
        dataIndex: "group_ids",
        key: "group_names",
        width: 200,
        render: (groupIds: number[]) => {
          const names = getGroupNames(groupIds);
          return (
            <div className="flex flex-wrap gap-1">
              {names.length > 0 ? (
                names.map((name, index) => (
                  <Tag key={index} color="cyan">
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
        title: t("tenantResources.invitation.capacity"),
        dataIndex: "capacity",
        key: "capacity",
        width: 100,
        render: (capacity: number) => <span>{capacity}</span>,
      },
      {
        title: t("tenantResources.invitation.used"),
        dataIndex: "used_times",
        key: "used_times",
        width: 80,
        render: (used: number) => <span>{used}</span>,
      },
      {
        title: t("tenantResources.invitation.expiryDate"),
        dataIndex: "expiry_date",
        key: "expiry_date",
        width: 130,
        render: (date: string) =>
          date ? dayjs(date).format("YYYY-MM-DD") : <span className="text-gray-400">{t("tenantResources.invitation.noExpiry")}</span>,
      },
      {
        title: t("tenantResources.invitation.status"),
        dataIndex: "status",
        key: "status",
        width: 120,
        render: (status: string) => {
          const color =
            status === "IN_USE" ? "green" :
            status === "EXPIRE" ? "gray" :
            status === "DISABLE" ? "red" : "orange";

          const icon = status === "IN_USE" ? <CheckCircle className="w-3 h-3 mr-1" /> :
                      status === "EXPIRE" ? <Clock className="w-3 h-3 mr-1" /> :
                      status === "DISABLE" ? <XCircle className="w-3 h-3 mr-1" /> :
                      <AlertCircle className="w-3 h-3 mr-1" />;

          return (
            <Tag color={color} className="flex items-center">
              {icon}
              {t(`tenantResources.invitation.status.${status}`)}
            </Tag>
          );
        },
      },
      {
        title: t("tenantResources.invitation.actions"),
        key: "actions",
        width: 120,
        fixed: "right",
        render: (_, record: Invitation) => (
          <div className="flex items-center space-x-3">
            <Tooltip title={t("tenantResources.invitation.editInvitation")}>
              <button
                onClick={() => openEdit(record)}
                className="text-gray-600 hover:text-blue-600 transition-colors cursor-pointer"
                aria-label={t("tenantResources.invitation.editInvitation")}
              >
                <Edit className="h-4 w-4" />
              </button>
            </Tooltip>
            <Popconfirm
              title={t("tenantResources.invitation.confirmDeleteInvitation", { code: record.invitation_code })}
              description={t("common.cannotBeUndone")}
              onConfirm={() => handleDelete(record.invitation_code)}
            >
              <Tooltip title={t("tenantResources.invitation.deleteInvitation")}>
                <button
                  className="text-gray-600 hover:text-red-600 transition-colors cursor-pointer"
                  aria-label={t("tenantResources.invitation.deleteInvitation")}
                >
                  <Trash2 className="h-4 w-4" />
                </button>
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
    <div>
      <div className="mb-4 flex justify-between items-center">
        <div />
        <div>
          <Button type="primary" onClick={openCreate} icon={<Plus className="h-4 w-4 mr-2" />}>
            {t("tenantResources.invitation.createInvitation")}
          </Button>
        </div>
      </div>

      {tenantId ? (
        // Single tenant view with pagination
        <>
          <Table
            columns={columns}
            dataSource={invitations}
            loading={isLoading}
            rowKey="invitation_id"
            pagination={false}
            scroll={{ x: 1000 }}
          />
          {total > pageSize && (
            <div className="mt-4 flex justify-center">
              <Pagination
                current={currentPage}
                pageSize={pageSize}
                total={total}
                showSizeChanger
                showQuickJumper
                showTotal={(total, range) =>
                  `Showing ${range[0]}-${range[1]} of ${total} invitations`
                }
                onChange={(page, size) => {
                  setCurrentPage(page);
                  setPageSize(size);
                }}
                onShowSizeChange={(current, size) => {
                  setCurrentPage(1);
                  setPageSize(size);
                }}
              />
            </div>
          )}
        </>
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
                pagination={false}
                size="small"
                scroll={{ x: 1000 }}
              />
            </Panel>
          ))}
        </Collapse>
      )}

      {/* Create/Edit Modal */}
      <Modal
        title={editingInvitation ? t("tenantResources.invitation.editInvitation") : t("tenantResources.invitation.createInvitation")}
        open={modalVisible}
        onOk={handleSubmit}
        onCancel={() => setModalVisible(false)}
        width={600}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="code_type"
            label={t("tenantResources.invitation.codeType")}
            rules={[{ required: true, message: t("tenantResources.invitation.codeTypeRequired") }]}
          >
            <Select placeholder={t("tenantResources.invitation.codeType")}>
              <Select.Option value="ADMIN_INVITE">{t("tenantResources.invitation.codeType.ADMIN_INVITE")}</Select.Option>
              <Select.Option value="DEV_INVITE">{t("tenantResources.invitation.codeType.DEV_INVITE")}</Select.Option>
              <Select.Option value="USER_INVITE">{t("tenantResources.invitation.codeType.USER_INVITE")}</Select.Option>
            </Select>
          </Form.Item>

          <Form.Item
            name="capacity"
            label={t("tenantResources.invitation.capacity")}
            rules={[
              { required: true, message: t("tenantResources.invitation.capacityRequired") },
              { type: "number", min: 1, message: t("tenantResources.invitation.capacityMin") }
            ]}
          >
            <Input type="number" placeholder={t("tenantResources.invitation.capacity")} min={1} />
          </Form.Item>

          <Form.Item
            name="invitation_code"
            label={t("tenantResources.invitation.invitationCode")}
            rules={[
              {
                pattern: /^[A-Z0-9]*$/,
                message: t("tenantResources.invitation.invitationCodeInvalid")
              }
            ]}
          >
            <Input
              placeholder={t("tenantResources.invitation.invitationCode")}
              onChange={(e) => {
                // Convert to uppercase and filter invalid characters
                const value = e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, "");
                form.setFieldsValue({ invitation_code: value });
              }}
            />
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
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

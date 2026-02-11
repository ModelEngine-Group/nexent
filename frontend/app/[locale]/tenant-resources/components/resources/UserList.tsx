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
} from "antd";
import { Edit, Trash2 } from "lucide-react";
import { Tooltip } from "@/components/ui/tooltip";
import { ColumnsType } from "antd/es/table";
import { useUserList } from "@/hooks/user/useUserList";
import { useGroupList } from "@/hooks/group/useGroupList";
import {
  updateUser,
  deleteUser,
  type User,
  type UpdateUserRequest,
} from "@/services/userService";
import {
  createGroup,
  type Group,
  type CreateGroupRequest,
} from "@/services/groupService";

export default function UserList({ tenantId }: { tenantId: string | null }) {
  const { t } = useTranslation("common");

  const { data, isLoading, refetch } = useUserList(tenantId);
  const { data: groupsData } = useGroupList(tenantId);

  const users = data?.users || [];
  const groups = groupsData?.groups || [];
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [modalVisible, setModalVisible] = useState(false);
  const [createGroupModalVisible, setCreateGroupModalVisible] = useState(false);

  const [form] = Form.useForm();
  const [groupForm] = Form.useForm();

  const openCreateGroup = () => {
    groupForm.resetFields();
    setCreateGroupModalVisible(true);
  };

  const openEdit = (u: User) => {
    setEditingUser(u);
    form.setFieldsValue({ username: u.username, role: u.role });
    setModalVisible(true);
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteUser(id.toString());
      message.success(t("tenantResources.users.deleted"));
      refetch();
    } catch (err: any) {
      if (err.response?.data?.message) {
        message.error(err.response.data.message);
      } else {
        message.error(t("common.unknownError"));
      }
    }
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      if (!tenantId) throw new Error("No tenant selected");

      if (editingUser) {
        const updateData: UpdateUserRequest = {
          role: values.role,
        };
        await updateUser(editingUser.id.toString(), updateData);
        message.success(t("tenantResources.users.updated"));
      }
      setModalVisible(false);
      form.resetFields();
      refetch();
    } catch (err: any) {
      // validation errors already shown by form
      if (err.response?.data?.message) {
        message.error(err.response.data.message);
      }
    }
  };

  const handleCreateGroup = async () => {
    try {
      const values = await groupForm.validateFields();
      if (!tenantId) throw new Error("No tenant selected");

      const groupData: CreateGroupRequest = {
        group_name: values.name,
        group_description: values.description,
      };

      const createdGroup = await createGroup(tenantId, groupData);
      message.success(t("tenantResources.groups.created"));

      setCreateGroupModalVisible(false);
      groupForm.resetFields();

      // Refresh groups list
      // Note: useGroupList will automatically refetch on tenant change
    } catch (err: any) {
      if (err.response?.data?.message) {
        message.error(err.response.data.message);
      }
    }
  };

  const columns: ColumnsType<User> = useMemo(
    () => [
      {
        title: t("common.email"),
        dataIndex: "username",
        key: "username",
      },
      {
        title: t("common.type"),
        dataIndex: "role",
        key: "role",
        render: (role: string) => {
          const roleLabels: Record<string, string> = {
            SUPER_ADMIN: t("user.role.superAdmin"),
            ADMIN: t("user.role.admin"),
            DEV: t("user.role.dev"),
            USER: t("user.role.user"),
          };
          const color =
            role === "SUPER_ADMIN" ? "magenta" :
            role === "ADMIN" ? "purple" :
            role === "DEV" ? "cyan" :
            role === "USER" ? "blue" : "gray";
          return <Tag color={color}>
              {roleLabels[role] || role}
            </Tag>;
        },
      },
      {
        title: t("common.actions"),
        key: "actions",
        render: (_, record) => (
          <div className="flex items-center space-x-2">
            <Tooltip title={t("tenantResources.users.editUser")}>
              <Button
                type="text"
                icon={<Edit className="h-4 w-4" />}
                onClick={() => openEdit(record)}
                size="small"
              />
            </Tooltip>
            <Popconfirm
              title={t("tenantResources.users.confirmDelete", {
                name: record.username,
              })}
              onConfirm={() => handleDelete(record.id)}
              okText={t("common.confirm")}
              cancelText={t("common.cancel")}
            >
              <Tooltip title={t("tenantResources.users.deleteUser")}>
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
    []
  );

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <Table
        dataSource={users}
        columns={columns}
        rowKey={(r) => String(r.id)}
        loading={isLoading}
        pagination={{ pageSize: 10 }}
        scroll={{ x: true }}
        className="flex-1"
      />

      <Modal
        title={t("tenantResources.users.editUser")}
        open={modalVisible}
        onOk={handleSubmit}
        onCancel={() => setModalVisible(false)}
        okText={t("common.confirm")}
        cancelText={t("common.cancel")}
      >
        <Form layout="vertical" form={form}>
          <Form.Item name="username" label={t("common.email")}>
            <Input
              disabled={!!editingUser}
              placeholder={t("tenantResources.users.enterEmail")}
            />
          </Form.Item>
          <Form.Item name="role" label={t("common.type")} rules={[{ required: true }]}>
            <Select
              options={[
                { label: t("user.role.admin"), value: "ADMIN" },
                { label: t("user.role.dev"), value: "DEV" },
                { label: t("user.role.user"), value: "USER" },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* Create Group Modal */}
      <Modal
        title={t("tenantResources.groups.createGroup")}
        open={createGroupModalVisible}
        onOk={handleCreateGroup}
        onCancel={() => setCreateGroupModalVisible(false)}
        okText={t("common.confirm")}
        cancelText={t("common.cancel")}
      >
        <Form layout="vertical" form={groupForm}>
          <Form.Item
            name="name"
            label={t("tenantResources.tenants.name")}
            rules={[{ required: true, message: "Please enter group name" }]}
          >
            <Input placeholder="Enter group name" />
          </Form.Item>
          <Form.Item name="description" label="Description">
            <Input.TextArea
              placeholder="Enter group description (optional)"
              rows={3}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

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
  Divider,
} from "antd";
import { EditOutlined, DeleteOutlined } from "@ant-design/icons";
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
  addUserToGroup,
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
      message.success(t("tenantResources.userDeleted"));
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
        message.success(t("tenantResources.userUpdated"));
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
      message.success(t("tenantResources.groupCreated"));

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
        title: "Email",
        dataIndex: "username",
        key: "username",
      },
      {
        title: "Role",
        dataIndex: "role",
        key: "role",
        render: (role: string) => {
          const roleLabels: Record<string, string> = {
            SUPER_ADMIN: t("user.role.superAdmin"),
            ADMIN: t("user.role.admin"),
            DEV: t("user.role.dev"),
            USER: t("user.role.user"),
          };
          return roleLabels[role] || role;
        },
      },
      {
        title: "Actions",
        key: "actions",
        render: (_, record) => (
          <div className="space-x-2">
            <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)} />
            <Popconfirm
              title={t("tenantResources.confirmDeleteUser", {
                name: record.username,
              })}
              onConfirm={() => handleDelete(record.id)}
            >
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          </div>
        ),
      },
    ],
    []
  );

  return (
    <div>
      <Table
        dataSource={users}
        columns={columns}
        rowKey={(r) => String(r.id)}
        loading={isLoading}
        pagination={{ pageSize: 10 }}
      />

      <Modal
        title={t("tenantResources.editUser")}
        open={modalVisible}
        onOk={handleSubmit}
        onCancel={() => setModalVisible(false)}
      >
        <Form layout="vertical" form={form}>
          <Form.Item name="username" label="Email">
            <Input
              disabled={!!editingUser}
              placeholder={
                editingUser ? "User email address" : "Enter user email address"
              }
            />
          </Form.Item>
          <Form.Item name="role" label="Role" rules={[{ required: true }]}>
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
        title={t("tenantResources.createGroup")}
        open={createGroupModalVisible}
        onOk={handleCreateGroup}
        onCancel={() => setCreateGroupModalVisible(false)}
      >
        <Form layout="vertical" form={groupForm}>
          <Form.Item
            name="name"
            label={t("tenantResources.tenantName")}
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

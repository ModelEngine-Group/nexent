"use client";

import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import {
  Table,
  Button,
  Modal,
  Form,
  Input,
  Popconfirm,
  message,
  Select,
} from "antd";
import { Edit, Trash2 } from "lucide-react";
import { Tooltip } from "@/components/ui/tooltip";
import { ColumnsType } from "antd/es/table";
import { useGroupList } from "@/hooks/group/useGroupList";
import { useUserList } from "@/hooks/user/useUserList";
import {
  createGroup,
  updateGroup,
  deleteGroup,
  addUserToGroup,
  removeUserFromGroup,
  getGroupMembers,
  updateGroupMembers,
  type Group,
  type CreateGroupRequest,
  type UpdateGroupRequest,
} from "@/services/groupService";
import { type User } from "@/services/userService";

export default function GroupList({ tenantId }: { tenantId: string | null }) {
  const { t } = useTranslation("common");
  const queryClient = useQueryClient();
  const { data, isLoading, refetch } = useGroupList(tenantId);
  const { data: userData, refetch: refetchUsers } = useUserList(
    tenantId,
    1,
    100
  ); // Get all users for member management
  const groups = data?.groups || [];
  const allUsers = userData?.users || [];
  const [editingGroup, setEditingGroup] = useState<Group | null>(null);
  const [modalVisible, setModalVisible] = useState(false);
  const [userListModalVisible, setUserListModalVisible] = useState(false);
  const [selectedGroupForUsers, setSelectedGroupForUsers] =
    useState<Group | null>(null);
  const [groupUsers, setGroupUsers] = useState<User[]>([]);
  const [availableUsers, setAvailableUsers] = useState<User[]>([]);
  const [editFormInitialValues, setEditFormInitialValues] = useState<{
    name: string;
    description: string;
    members: string[];
  } | null>(null);

  const [form] = Form.useForm();
  const [editGroupForm] = Form.useForm();

  const openCreate = () => {
    setEditingGroup(null);
    form.resetFields();
    setModalVisible(true);
  };

  const openEdit = async (g: Group) => {
    try {
      const members = await getGroupMembers(g.group_id);
      setGroupUsers(members);
      const memberIds = new Set(members.map((u) => u.id));
      setAvailableUsers(allUsers.filter((u) => !memberIds.has(u.id)));

      const formValues = {
        name: g.group_name || "",
        description: (g.group_description || "").toString(),
        members: members.map((u) => u.id),
      };
      setEditFormInitialValues(formValues);
      setEditingGroup(g);
      editGroupForm.resetFields();
      editGroupForm.setFieldsValue(formValues);
    } catch (error) {
      message.error("Failed to load group members");
      setGroupUsers([]);
      setAvailableUsers(allUsers);
      const formValues = {
        name: g.group_name || "",
        description: (g.group_description || "").toString(),
        members: [],
      };
      setEditFormInitialValues(formValues);
      setEditingGroup(g);
      editGroupForm.resetFields();
      editGroupForm.setFieldsValue(formValues);
    }

    setModalVisible(true);
  };

  const openUserList = async (g: Group) => {
    setSelectedGroupForUsers(g);
    try {
      const members = await getGroupMembers(g.group_id);
      setGroupUsers(members);
    } catch (error) {
      message.error("Failed to load group users");
      setGroupUsers([]);
    }
    setUserListModalVisible(true);
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteGroup(id);
      message.success("Group deleted");
      // Invalidate all group queries to ensure all components get updated data
      queryClient.invalidateQueries({ queryKey: ["groups"] });
    } catch (err: any) {
      if (err.response?.data?.message) {
        message.error(err.response.data.message);
      } else {
        message.error("Delete failed");
      }
    }
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();
      if (!tenantId) throw new Error("No tenant selected");

      if (editingGroup) {
        const updateData: UpdateGroupRequest = {
          group_name: values.name,
          group_description: values.description,
        };
        await updateGroup(editingGroup.group_id, updateData);
        message.success("Group updated");
      } else {
        const createData: CreateGroupRequest = {
          group_name: values.name,
          group_description: values.description,
        };
        await createGroup(tenantId, createData);
        message.success("Group created");
      }
      setModalVisible(false);
      // Invalidate all group queries to ensure all components get updated data
      queryClient.invalidateQueries({ queryKey: ["groups"] });
    } catch (err: any) {
      const errorMessage = err?.response?.data?.message || err?.message || "";
      const nameConflictMatch = errorMessage.match(/Group with name '(.*)' already exists/i) ||
                                errorMessage.match(/Group name '(.*)' already exists/i);

      if (nameConflictMatch && nameConflictMatch[1]) {
        message.error(t("tenantResources.groups.duplicateName"));
      } else if (err.response?.data?.message) {
        message.error(err.response.data.message);
      }
    }
  };

  const handleEditGroupSubmit = async () => {
    try {
      if (!editingGroup) return;

      await editGroupForm.validateFields();
      const values = editGroupForm.getFieldsValue(true);

      const updateData: UpdateGroupRequest = {
        group_name: values.name,
        group_description: values.description,
      };
      await updateGroup(editingGroup.group_id, updateData);

      const newMemberIds = (values.members as string[]) || [];
      await updateGroupMembers(editingGroup.group_id, newMemberIds);

      message.success(t("tenantResources.groups.updated"));
      setModalVisible(false);

      // Invalidate all group queries to ensure all components get updated data
      queryClient.invalidateQueries({ queryKey: ["groups"] });
      // Refresh user list in case user roles/status changed
      await refetchUsers();
    } catch (err: any) {
      const errorMessage = err?.response?.data?.message || err?.message || "";
      const nameConflictMatch = errorMessage.match(/Group with name '(.*)' already exists/i) ||
                                errorMessage.match(/Group name '(.*)' already exists/i);

      if (nameConflictMatch && nameConflictMatch[1]) {
        message.error(t("tenantResources.groups.duplicateName"));
      } else if (err.response?.data?.message) {
        message.error(err.response.data.message);
      } else {
        message.error("Failed to update group");
      }
    }
  };

  const columns: ColumnsType<Group> = useMemo(
    () => [
      { title: t("tenantResources.groups.name"), dataIndex: "group_name", key: "group_name" },
      {
        title: t("common.description"),
        dataIndex: "group_description",
        key: "group_description",
        render: (description: string) =>
          description ? description : <span className="text-gray-400">{t("tenantResources.groups.noDescription")}</span>,
      },
      {
        title: t("tenantResources.groups.members"),
        dataIndex: "user_count",
        key: "user_count",
        render: (count: number, record: Group) => (
          <Button
            type="link"
            size="small"
            onClick={() => openUserList(record)}
            style={{ padding: 0 }}
          >
            {count || 0}
          </Button>
        ),
      },
      {
        title: t("common.actions"),
        key: "actions",
        render: (_, record) => (
          <div className="flex items-center space-x-2">
            <Tooltip title={t("tenantResources.groups.editGroup")}>
              <Button
                type="text"
                icon={<Edit className="h-4 w-4" />}
                onClick={() => openEdit(record)}
                size="small"
              />
            </Tooltip>
            <Popconfirm
              title={t("tenantResources.groups.confirmDelete", {
                name: record.group_name,
              })}
              onConfirm={() => handleDelete(record.group_id)}
              okText={t("common.confirm")}
              cancelText={t("common.cancel")}
            >
              <Tooltip title={t("tenantResources.groups.deleteGroup")}>
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
    [t]
  );

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="flex items-center justify-between mb-4 flex-shrink-0">
        <div />
        <div>
          <Button type="primary" onClick={openCreate}>
            + {t("tenantResources.groups.createGroup")}
          </Button>
        </div>
      </div>

      <Table
        dataSource={groups}
        columns={columns}
        rowKey={(r) => String(r.group_id)}
        loading={isLoading}
        pagination={{ pageSize: 10 }}
        scroll={{ x: true }}
        className="flex-1"
      />

      {/* Create/Edit Group Modal */}
      <Modal
        title={
          editingGroup
            ? t("tenantResources.groups.editGroup")
            : t("tenantResources.groups.createGroup")
        }
        open={modalVisible}
        onOk={editingGroup ? handleEditGroupSubmit : handleSubmit}
        onCancel={() => {
          setModalVisible(false);
          editGroupForm.resetFields();
        }}
        destroyOnClose
        okText={t("common.confirm")}
        cancelText={t("common.cancel")}
        width={editingGroup ? 600 : 400}
      >
        {editingGroup ? (
          <Form
            key={editingGroup.group_id}
            layout="vertical"
            form={editGroupForm}
          >
            <Form.Item
              name="name"
              label={t("tenantResources.tenants.name")}
              rules={[{ required: true }]}
            >
              <Input placeholder={t("tenantResources.tenants.name")} />
            </Form.Item>
            <Form.Item name="description" label={t("common.description")}>
              <Input.TextArea placeholder={t("common.description")} rows={3} />
            </Form.Item>
            <Form.Item name="members" label={t("tenantResources.groups.members")}>
              <Select
                mode="multiple"
                placeholder={t("tenantResources.groups.selectUsers")}
                options={allUsers.map((user) => ({
                  label: user.username,
                  value: user.id,
                }))}
                onChange={(value) => {
                  const selectedUsers = allUsers.filter((u) =>
                    value.includes(u.id)
                  );
                  setGroupUsers(selectedUsers);
                  const memberIds = new Set(selectedUsers.map((u) => u.id));
                  setAvailableUsers(
                    allUsers.filter((u) => !memberIds.has(u.id))
                  );
                }}
              />
            </Form.Item>
          </Form>
        ) : (
          <Form layout="vertical" form={form}>
            <Form.Item
              name="name"
              label={t("tenantResources.groups.name")}
              rules={[{ required: true }]}
            >
            <Input placeholder={t("tenantResources.groups.enterName")} />
            </Form.Item>
            <Form.Item name="description" label={t("common.description")}>
              <Input.TextArea
                placeholder={t("common.description")}
                rows={3}
              />
            </Form.Item>
          </Form>
        )}
      </Modal>

      {/* User List Modal */}
      <Modal
        title={`${t("tenantResources.groups.members")} - ${selectedGroupForUsers?.group_name}`}
        open={userListModalVisible}
        onCancel={() => setUserListModalVisible(false)}
        footer={null}
        width={500}
      >
        <div>
          <p style={{ marginBottom: 16 }}>
            {t("tenantResources.groups.totalMembers")}: {groupUsers.length}
          </p>
          {groupUsers.length > 0 ? (
            <div style={{ maxHeight: 300, overflowY: "auto" }}>
              {groupUsers.map((user) => (
                <div
                  key={user.id}
                  style={{
                    padding: "8px 12px",
                    border: "1px solid #d9d9d9",
                    borderRadius: 4,
                    marginBottom: 8,
                    backgroundColor: "#fafafa",
                  }}
                >
                  {user.username}
                </div>
              ))}
            </div>
          ) : (
            <p style={{ color: "#999", fontStyle: "italic" }}>
              {t("tenantResources.groups.noMembers")}
            </p>
          )}
        </div>
      </Modal>
    </div>
  );
}

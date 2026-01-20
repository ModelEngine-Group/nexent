"use client";

import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
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
  type Group,
  type CreateGroupRequest,
  type UpdateGroupRequest,
} from "@/services/groupService";
import { type User } from "@/services/userService";

export default function GroupList({ tenantId }: { tenantId: string | null }) {
  const { t } = useTranslation("common");
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

  const [form] = Form.useForm();
  const [editGroupForm] = Form.useForm();

  const openCreate = () => {
    setEditingGroup(null);
    form.resetFields();
    setModalVisible(true);
  };

  const openEdit = async (g: Group) => {
    setEditingGroup(g);
    editGroupForm.setFieldsValue({
      name: g.group_name,
      description: g.group_description || "",
    });

    // Load current group members
    try {
      const members = await getGroupMembers(g.group_id);
      setGroupUsers(members);
      // Available users are all users minus current members
      const memberIds = new Set(members.map((u) => u.id));
      setAvailableUsers(allUsers.filter((u) => !memberIds.has(u.id)));
    } catch (error) {
      message.error("Failed to load group members");
      setGroupUsers([]);
      setAvailableUsers(allUsers);
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
      refetch();
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
        };
        await updateGroup(editingGroup.group_id, updateData);
        message.success("Group updated");
      } else {
        const createData: CreateGroupRequest = {
          group_name: values.name,
        };
        await createGroup(tenantId, createData);
        message.success("Group created");
      }
      setModalVisible(false);
      refetch();
    } catch (err: any) {
      if (err.response?.data?.message) {
        message.error(err.response.data.message);
      }
    }
  };

  const handleEditGroupSubmit = async () => {
    try {
      const values = await editGroupForm.validateFields();
      if (!editingGroup) return;

      // Update group info
      const updateData: UpdateGroupRequest = {
        group_name: values.name,
        group_description: values.description,
      };
      await updateGroup(editingGroup.group_id, updateData);

      // Handle user additions/removals
      const currentMemberIds = new Set(groupUsers.map((u) => u.id));
      const newMemberIds = new Set((values.members as string[]) || []);

      // Add new members
      for (const userId of newMemberIds) {
        if (!currentMemberIds.has(userId)) {
          await addUserToGroup(editingGroup.group_id, userId);
        }
      }

      // Remove old members
      for (const user of groupUsers) {
        if (!newMemberIds.has(user.id)) {
          await removeUserFromGroup(editingGroup.group_id, user.id.toString());
        }
      }

      message.success(t("tenantResources.groupUpdated"));
      setModalVisible(false);
      refetch();
      refetchUsers();
    } catch (err: any) {
      if (err.response?.data?.message) {
        message.error(err.response.data.message);
      } else {
        message.error("Failed to update group");
      }
    }
  };

  const columns: ColumnsType<Group> = useMemo(
    () => [
      { title: "Group", dataIndex: "group_name", key: "group_name" },
      {
        title: "Description",
        dataIndex: "group_description",
        key: "group_description",
      },
      {
        title: "Users",
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
        title: "Actions",
        key: "actions",
        render: (_, record) => (
          <div className="space-x-2">
            <Button size="small" onClick={() => openEdit(record)}>
              {t("common.edit")}
            </Button>
            <Popconfirm
              title={t("tenantResources.confirmDeleteGroup", {
                name: record.group_name,
              })}
              onConfirm={() => handleDelete(record.group_id)}
            >
              <Button size="small" danger>
                {t("common.delete")}
              </Button>
            </Popconfirm>
          </div>
        ),
      },
    ],
    []
  );

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div />
        <div>
          <Button type="primary" onClick={openCreate}>
            + {t("tenantResources.createGroup")}
          </Button>
        </div>
      </div>

      <Table
        dataSource={groups}
        columns={columns}
        rowKey={(r) => String(r.group_id)}
        loading={isLoading}
        pagination={{ pageSize: 10 }}
      />

      {/* Create/Edit Group Modal */}
      <Modal
        title={
          editingGroup
            ? t("tenantResources.editGroup")
            : t("tenantResources.createGroup")
        }
        open={modalVisible}
        onOk={editingGroup ? handleEditGroupSubmit : handleSubmit}
        onCancel={() => setModalVisible(false)}
        width={editingGroup ? 600 : 400}
      >
        {editingGroup ? (
          <Form layout="vertical" form={editGroupForm}>
            <Form.Item
              name="name"
              label={t("tenantResources.tenantName")}
              rules={[{ required: true }]}
            >
              <Input placeholder={t("tenantResources.tenantName")} />
            </Form.Item>
            <Form.Item name="description" label={t("common.description")}>
              <Input.TextArea placeholder={t("common.description")} rows={3} />
            </Form.Item>
            <Form.Item name="members" label={t("tenantResources.groupMembers")}>
              <Select
                mode="multiple"
                placeholder={t("tenantResources.selectUsers")}
                options={allUsers.map((user) => ({
                  label: user.username,
                  value: user.id,
                }))}
                value={groupUsers.map((u) => u.id)}
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
              label={t("tenantResources.tenantName")}
              rules={[{ required: true }]}
            >
              <Input placeholder={t("tenantResources.tenantName")} />
            </Form.Item>
          </Form>
        )}
      </Modal>

      {/* User List Modal */}
      <Modal
        title={`${t("tenantResources.groupMembers")} - ${selectedGroupForUsers?.group_name}`}
        open={userListModalVisible}
        onCancel={() => setUserListModalVisible(false)}
        footer={null}
        width={500}
      >
        <div>
          <p style={{ marginBottom: 16 }}>
            {t("tenantResources.totalMembers")}: {groupUsers.length}
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
              {t("tenantResources.noGroupMembers")}
            </p>
          )}
        </div>
      </Modal>
    </div>
  );
}

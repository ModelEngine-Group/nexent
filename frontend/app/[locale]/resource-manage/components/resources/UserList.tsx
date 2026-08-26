"use client";

import React, { useMemo, useState, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import {
  Table,
  Button,
  Modal,
  Form,
  Input,
  Select,
  message,
  Tag,
  Tooltip,
} from "antd";
import { Edit, Trash2 } from "lucide-react";
import { ColumnsType } from "antd/es/table";
import { useUserList } from "@/hooks/user/useUserList";
import { useGroupList } from "@/hooks/group/useGroupList";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import {
  updateUser,
  deleteUser,
  type User,
  type UpdateUserRequest,
} from "@/services/userService";
import {
  createGroup,
  addUserToGroup,
  removeUserFromGroup,
  type Group,
  type CreateGroupRequest,
} from "@/services/groupService";

export default function UserList({ tenantId, refreshKey }: { tenantId: string | null; refreshKey?: number }) {
  const { confirm } = useConfirmModal();
  const { t } = useTranslation("common");

  // Pagination state
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [keyword, setKeyword] = useState("");
  const [roleFilters, setRoleFilters] = useState<string[]>([]);
  const [groupFilters, setGroupFilters] = useState<number[]>([]);

  const { data, isLoading, refetch } = useUserList(tenantId, page, pageSize, {
    search: keyword,
    roles: roleFilters,
    groupIds: groupFilters,
  });
  const { data: groupsData } = useGroupList(tenantId);

  // Reset page to 1 when tenantId changes
  useEffect(() => {
    setPage(1);
    setKeyword("");
    setRoleFilters([]);
    setGroupFilters([]);
  }, [tenantId]);

  const resetFilters = () => {
    setPage(1);
    setKeyword("");
    setRoleFilters([]);
    setGroupFilters([]);
  };

  // Trigger refetch when refreshKey changes
  useEffect(() => {
    if (refreshKey && refreshKey > 0 && tenantId) {
      refetch();
    }
  }, [refreshKey, tenantId, refetch]);

  const users = data?.users || [];
  const total = data?.total || 0;
  const groups = groupsData?.groups || [];
  // Refs to break stale closures inside useMemo([]) handlers below
  const groupsRef = useRef(groups);
  groupsRef.current = groups;
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const editingUserRef = useRef(editingUser);
  editingUserRef.current = editingUser;
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
    const currentGroupIds = groupsRef.current
      .filter((g) => u.group_names?.includes(g.group_name))
      .map((g) => g.group_id);
    form.setFieldsValue({
      username: u.username,
      role: u.role,
      group_ids: currentGroupIds,
    });
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

      if (editingUserRef.current) {
        const eu = editingUserRef.current;
        const updateData: UpdateUserRequest = {
          role: values.role,
        };
        await updateUser(eu.id.toString(), updateData);

        // Sync group membership changes
        const selectedGroupIds: number[] = values.group_ids || [];
        const previousGroupIds = groupsRef.current
          .filter((g) => eu.group_names?.includes(g.group_name))
          .map((g) => g.group_id);

        const toAdd = selectedGroupIds.filter(
          (id) => !previousGroupIds.includes(id)
        );
        const toRemove = previousGroupIds.filter(
          (id) => !selectedGroupIds.includes(id)
        );

        await Promise.all([
          ...toAdd.map((gid) => addUserToGroup(gid, eu.id)),
          ...toRemove.map((gid) => removeUserFromGroup(gid, eu.id)),
        ]);

        message.success(t("tenantResources.users.updated"));
      }
      setModalVisible(false);
      form.resetFields();
      refetch();
    } catch (err: any) {
      message.error(
        err?.message || err?.response?.data?.message || t("common.unknownError")
      );
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
      message.error(
        err?.message || err?.response?.data?.message || t("common.unknownError")
      );
    }
  };

  const columns: ColumnsType<User> = useMemo(
    () => [
      {
        title: t("common.email"),
        dataIndex: "username",
        key: "username",
        width: "30%",
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
            ASSET_OWNER: t("user.role.assetOwner"),
          };
          const color =
            role === "SUPER_ADMIN"
              ? "magenta"
              : role === "ADMIN"
                ? "purple"
                : role === "DEV"
                  ? "cyan"
                  : role === "USER"
                    ? "blue"
                    : role === "ASSET_OWNER"
                      ? "gold"
                      : "gray";
          return <Tag color={color}>{roleLabels[role] || role}</Tag>;
        },
        width: "20%",
      },
      {
        title: t("tenantResources.users.userGroup"),
        dataIndex: "group_names",
        key: "group_names",
        render: (groupNames: string[] | undefined) => {
          if (!groupNames || groupNames.length === 0) {
            return "-";
          }
          return (
            <div className="flex flex-wrap gap-1">
              {groupNames.map((name) => (
                <Tag key={name} color="geekblue">
                  {name}
                </Tag>
              ))}
            </div>
          );
        },
        width: "20%",
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
            <Tooltip title={t("tenantResources.users.deleteUser")}>
              <Button
                type="text"
                danger
                icon={<Trash2 className="h-4 w-4" />}
                size="small"
                onClick={() =>
                  confirm({
                    title: t("tenantResources.users.confirmDelete", {
                      name: record.username,
                    }),
                    content: "",
                    okText: t("common.confirm"),
                    cancelText: t("common.cancel"),
                    onOk: () => handleDelete(record.id),
                  })
                }
              />
            </Tooltip>
          </div>
        ),
        width: "30%",
      },
    ],
    []
  );

  const handlePageChange = (newPage: number, newPageSize: number) => {
    setPage(newPage);
    if (newPageSize !== pageSize) {
      setPageSize(newPageSize);
      setPage(1);
    }
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="mb-4 flex items-center gap-3">
        <Input.Search
          allowClear
          value={keyword}
          onChange={(event) => {
            setPage(1);
            setKeyword(event.target.value);
          }}
          placeholder={t("tenantResources.users.searchPlaceholder")}
          className="w-56"
        />
        <Select
          mode="multiple"
          allowClear
          value={roleFilters}
          onChange={(values) => {
            setPage(1);
            setRoleFilters(values);
          }}
          options={[
            { label: t("user.role.superAdmin"), value: "SU" },
            { label: t("user.role.admin"), value: "ADMIN" },
            { label: t("user.role.dev"), value: "DEV" },
            { label: t("user.role.user"), value: "USER" },
            { label: t("user.role.assetOwner"), value: "ASSET_OWNER" },
          ]}
          placeholder={t("tenantResources.users.filterRole")}
          className="w-40"
        />
        <Select
          mode="multiple"
          allowClear
          value={groupFilters}
          onChange={(values) => {
            setPage(1);
            setGroupFilters(values);
          }}
          options={groups.map((group) => ({
            label: group.group_name,
            value: group.group_id,
          }))}
          placeholder={t("tenantResources.users.filterGroup")}
          className="w-52"
          showSearch
          optionFilterProp="label"
        />
        {(keyword || roleFilters.length > 0 || groupFilters.length > 0) && (
          <Button type="link" onClick={resetFilters}>
            {t("tenantResources.users.clearFilters")}
          </Button>
        )}
      </div>
      <Table
        dataSource={users}
        columns={columns}
        rowKey={(r) => String(r.id)}
        loading={isLoading}
        pagination={{
          current: page,
          pageSize: pageSize,
          total,
          onChange: handlePageChange,
        }}
        className="flex-1 [&_.ant-table]:h-full"
        scroll={{ y: "calc(100vh - 480px)" }}
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
          <Form.Item
            name="role"
            label={t("common.type")}
            rules={[{ required: true }]}
          >
            <Select
              options={[
                { label: t("user.role.admin"), value: "ADMIN" },
                { label: t("user.role.dev"), value: "DEV" },
                { label: t("user.role.user"), value: "USER" },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="group_ids"
            label={t("tenantResources.users.userGroup")}
          >
            <Select
              mode="multiple"
              showSearch={{ optionFilterProp: "label" }}
              placeholder={t("tenantResources.groups.selectUsers")}
              options={groups.map((g) => ({
                label: g.group_name,
                value: g.group_id,
              }))}
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
            label={t("tenantResources.groups.name")}
            rules={[
              {
                required: true,
                message: t("tenantResources.groups.enterName"),
              },
            ]}
          >
            <Input placeholder={t("tenantResources.groups.enterName")} />
          </Form.Item>
          <Form.Item name="description" label={t("common.description")}>
            <Input.TextArea
              placeholder={t("tenantResources.groups.enterDescription")}
              rows={3}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

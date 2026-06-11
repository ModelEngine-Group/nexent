"use client";

import React, { useMemo, useState, useEffect } from "react";
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
  Tooltip
} from "antd";
import { Edit, Trash2 } from "lucide-react";
import { ColumnsType } from "antd/es/table";
import { useUserList } from "@/hooks/user/useUserList";
import {
  updateUser,
  deleteUser,
  createUser,
  type User,
  type UpdateUserRequest,
  type CreateUserRequest,
} from "@/services/userService";
import {
  getPasswordChecks,
  getStrengthLevel,
  validatePassword as validatePasswordUtil,
} from "@/lib/utils";

export default function UserList({ tenantId, refreshKey }: { tenantId: string | null; refreshKey?: number }) {
  const { t } = useTranslation("common");

  // Pagination state
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  const { data, isLoading, refetch } = useUserList(tenantId, page, pageSize);

  // Reset page to 1 when tenantId changes
  useEffect(() => {
    setPage(1);
  }, [tenantId]);

  // Trigger refetch when refreshKey changes
  useEffect(() => {
    if (refreshKey && refreshKey > 0 && tenantId) {
      refetch();
    }
  }, [refreshKey, tenantId, refetch]);

  const users = data?.users || [];
  const total = data?.total || 0;
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [modalVisible, setModalVisible] = useState(false);
  const [createUserModalVisible, setCreateUserModalVisible] = useState(false);

  // Password validation state for add user
  const [addUserPasswordValue, setAddUserPasswordValue] = useState("");
  const [addUserPasswordError, setAddUserPasswordError] = useState<{
    target: "addUserPassword" | "confirmAddUserPassword" | "";
    message: string;
  }>({ target: "", message: "" });

  const [form] = Form.useForm();
  const [addUserForm] = Form.useForm();

  const openCreateUser = () => {
    addUserForm.resetFields();
    setAddUserPasswordValue("");
    setAddUserPasswordError({ target: "", message: "" });
    setCreateUserModalVisible(true);
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

  const handleAddUserPasswordChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setAddUserPasswordValue(value);

    if (value && !validatePasswordUtil(value)) {
      setAddUserPasswordError({
        target: "addUserPassword",
        message: t("auth.passwordStrengthError") || "Password must contain uppercase, lowercase, and digit",
      });
      return;
    }

    setAddUserPasswordError({ target: "", message: "" });
    const confirmPassword = addUserForm.getFieldValue("confirmPassword");
    if (confirmPassword && confirmPassword !== value) {
      setAddUserPasswordError({
        target: "confirmAddUserPassword",
        message: t("auth.passwordsDoNotMatch"),
      });
    }
  };

  const handleConfirmAddUserPasswordChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    const password = addUserForm.getFieldValue("password");

    if (password && !validatePasswordUtil(password)) {
      setAddUserPasswordError({
        target: "addUserPassword",
        message: t("auth.passwordStrengthError") || "Password must contain uppercase, lowercase, and digit",
      });
      return;
    }

    if (value && value !== password) {
      setAddUserPasswordError({
        target: "confirmAddUserPassword",
        message: t("auth.passwordsDoNotMatch"),
      });
    } else {
      setAddUserPasswordError({ target: "", message: "" });
    }
  };

  const handleAddUser = async () => {
    try {
      const values = await addUserForm.validateFields();

      const userData: CreateUserRequest = {
        email: values.email,
        password: values.password,
        role: values.role,
      };

      await createUser(userData);
      message.success(t("tenantResources.users.created"));

      setCreateUserModalVisible(false);
      addUserForm.resetFields();
      setAddUserPasswordValue("");
      setAddUserPasswordError({ target: "", message: "" });
      refetch();
    } catch (err: any) {
      const errorMessage = err?.response?.data?.detail || err?.message || "";
      if (errorMessage.includes("EMAIL_ALREADY_EXISTS")) {
        message.error(t("tenantResources.users.emailAlreadyExists"));
      } else if (err.response?.data?.message) {
        message.error(err.response.data.message);
      } else {
        message.error(t("common.unknownError"));
      }
    }
  };

  const columns: ColumnsType<User> = useMemo(
    () => [
      {
        title: t("common.email"),
        dataIndex: "username",
        key: "username",
        width: "50%"
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
            role === "SUPER_ADMIN" ? "magenta" :
            role === "ADMIN" ? "purple" :
            role === "DEV" ? "cyan" :
            role === "USER" ? "blue" :
            role === "ASSET_OWNER" ? "gold" : "gray";
          return <Tag color={color}>
              {roleLabels[role] || role}
            </Tag>;
        },
        width: "20%"
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
        width: "20%"
      },
    ],
    []
  );

  const handlePageChange = (newPage: number, _pageSize: number) => {
    setPage(newPage);
  };

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex items-center justify-between mb-4 flex-shrink-0">
        <div />
        <div>
          <Button type="primary" onClick={openCreateUser} style={{ display: "none" }}>
            + {t("tenantResources.users.addUser")}
          </Button>
        </div>
      </div>

      <Table
        dataSource={users}
        columns={columns}
        rowKey={(r) => String(r.id)}
        loading={isLoading}
        pagination={{
          current: page,
          pageSize: pageSize,
          total: total,
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

      {/* Add User Modal */}
      <Modal
        title={t("tenantResources.users.addUser")}
        open={createUserModalVisible}
        onOk={handleAddUser}
        onCancel={() => setCreateUserModalVisible(false)}
        okText={t("common.confirm")}
        cancelText={t("common.cancel")}
        width={480}
      >
        <Form layout="vertical" form={addUserForm}>
          <Form.Item
            name="email"
            label={t("common.email")}
            rules={[
              { required: true, message: t("common.required") },
              { type: "email", message: t("auth.invalidEmailFormat") || "Invalid email format" },
            ]}
          >
            <Input placeholder={t("tenantResources.users.enterEmail")} />
          </Form.Item>

          <Form.Item
            name="role"
            label={t("common.type")}
            rules={[{ required: true, message: t("common.required") }]}
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
            name="password"
            label={t("auth.passwordLabel")}
            validateStatus={addUserPasswordError.target === "addUserPassword" ? "error" : ""}
            help={
              addUserForm.getFieldError("password").length
                ? undefined
                : addUserPasswordError.target === "addUserPassword"
                  ? addUserPasswordError.message
                  : undefined
            }
            rules={[
              { required: true, message: t("auth.passwordRequired") || "Password is required" },
              {
                validator: (_, value) => {
                  if (!value) return Promise.resolve();
                  if (!validatePasswordUtil(value)) {
                    return Promise.reject(
                      new Error(
                        t("auth.passwordStrengthError") ||
                          "Password must contain uppercase, lowercase, and digit"
                      )
                    );
                  }
                  return Promise.resolve();
                },
              },
            ]}
            hasFeedback
          >
            <Input.Password
              placeholder={t("auth.passwordLabel")}
              autoComplete="new-password"
              onChange={handleAddUserPasswordChange}
            />
          </Form.Item>

          {/* Password Strength Indicator */}
          {addUserPasswordValue && addUserForm.getFieldValue("password") === addUserPasswordValue && (() => {
              const checks = getPasswordChecks(addUserPasswordValue);
              const levelInfo = getStrengthLevel(addUserPasswordValue, t);
              return (
                <div className="mb-4">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-gray-500">
                      {t("auth.passwordStrength") || "Password strength"}
                    </span>
                    <span
                      className="text-xs font-medium"
                      style={{ color: levelInfo.color }}
                    >
                      {levelInfo.label}
                    </span>
                  </div>
                  <div className="flex gap-1">
                    {[0, 1, 2, 3].map((level) => (
                      <div
                        key={level}
                        className="h-1 flex-1 rounded-full transition-colors"
                        style={{
                          backgroundColor:
                            level <= levelInfo.level ? levelInfo.color : "#e5e7eb",
                        }}
                      />
                    ))}
                  </div>
                </div>
              );
            })()}

          <Form.Item
            name="confirmPassword"
            label={t("auth.confirmPasswordLabel")}
            validateStatus={addUserPasswordError.target === "confirmAddUserPassword" ? "error" : ""}
            help={
              addUserPasswordError.target === "confirmAddUserPassword"
                ? addUserPasswordError.message
                : undefined
            }
            dependencies={["password"]}
            rules={[
              { required: true, message: t("auth.passwordRequired") || "Password is required" },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  const password = getFieldValue("password");
                  if (password && !validatePasswordUtil(password)) {
                    setAddUserPasswordError({
                      target: "addUserPassword",
                      message:
                        t("auth.passwordStrengthError") ||
                        "Password must contain uppercase, lowercase, and digit",
                    });
                    return Promise.reject(
                      new Error(
                        t("auth.passwordStrengthError") ||
                          "Password must contain uppercase, lowercase, and digit"
                      )
                    );
                  }
                  if (!value || getFieldValue("password") === value) {
                    return Promise.resolve();
                  }
                  return Promise.reject(
                    new Error(t("auth.passwordsDoNotMatch"))
                  );
                },
              }),
            ]}
            hasFeedback
          >
            <Input.Password
              placeholder={t("auth.confirmPasswordLabel")}
              autoComplete="new-password"
              onChange={handleConfirmAddUserPasswordChange}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

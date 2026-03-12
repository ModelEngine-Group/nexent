"use client";

import React, { useState, useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Row,
  Col,
  Tabs,
  Button,
  App,
  Modal,
  Form,
  Input,
  message,
  Switch,
  Spin,
  Pagination,
  Alert,
  Space,
} from "antd";
import { Users, Plus, Edit, Edit2, Building2, Trash2, AlertTriangle } from "lucide-react";
import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { useTenantList } from "@/hooks/tenant/useTenantList";
import {
  type Tenant,
  createTenant,
  updateTenant,
  deleteTenant,
  getTenantUsers,
  getTenant,
} from "@/services/tenantService";
import { createInvitation, deleteInvitation } from "@/services/invitationService";
import { authService } from "@/services/authService";
import UserList from "./resources/UserList";
import GroupList from "./resources/GroupList";
import ModelList from "./resources/ModelList";
import KnowledgeList from "./resources/KnowledgeList";
import InvitationList from "./resources/InvitationList";
import AgentList from "./resources/AgentList";
import McpList from "./resources/McpList";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { USER_ROLES } from "@/const/auth";
import { Can } from "@/components/permission/Can";

// Default page size for pagination
const DEFAULT_PAGE_SIZE = 20;

// Removed mockTenants - now using real data from API

function TenantList({
  selected,
  onSelect,
  tenants,
  total,
  page,
  pageSize,
  totalPages,
  onPageChange,
  onTenantsRefetch,
  loading,
  t,
  onUserListRefresh,
  onInvitationListRefresh,
}: {
  selected: string | null;
  onSelect: (id: string) => void;
  tenants: Tenant[];
  total?: number;
  page?: number;
  pageSize?: number;
  totalPages?: number;
  onPageChange?: (page: number) => void;
  onTenantsRefetch: () => Promise<unknown>;
  loading?: boolean;
  t: (key: string, options?: any) => string;
    onUserListRefresh?: () => void;
    onInvitationListRefresh?: () => void;
}) {
  const [editingTenant, setEditingTenant] = useState<Tenant | null>(null);
  const [modalVisible, setModalVisible] = useState(false);
  const [form] = Form.useForm();

  // State for generate admin account feature
  const [generateAdminAccount, setGenerateAdminAccount] = useState(false);

  // Delete modal state
  const [deleteModalVisible, setDeleteModalVisible] = useState(false);
  const [deletingTenant, setDeletingTenant] = useState<Tenant | null>(null);
  const [tenantUsers, setTenantUsers] = useState<any[]>([]);
  const [deleteLoading, setDeleteLoading] = useState(false);

  // Handle scroll event for infinite loading
  const openCreate = () => {
    setEditingTenant(null);
    form.resetFields();
    setGenerateAdminAccount(false);
    setModalVisible(true);
  };

  const openEdit = (tenant: Tenant) => {
    setEditingTenant(tenant);
    form.setFieldsValue({ name: tenant.tenant_name });
    setModalVisible(true);
  };

  // Handle delete button click - show warning modal with users list
  const handleDeleteClick = async (tenant: Tenant) => {
    setDeletingTenant(tenant);
    setDeleteLoading(true);
    setDeleteModalVisible(true);

    try {
      // Fetch users for this tenant
      const usersData = await getTenantUsers(tenant.tenant_id);
      setTenantUsers(usersData.users || []);
    } catch (error) {
      console.error("Failed to fetch tenant users:", error);
      setTenantUsers([]);
    } finally {
      setDeleteLoading(false);
    }
  };

  // Handle actual delete confirmation
  const handleDeleteConfirm = async () => {
    if (!deletingTenant) return;

    try {
      await deleteTenant(deletingTenant.tenant_id);
      message.success(t("tenantResources.tenants.deleted"));

      // Refresh the tenant list
      await onTenantsRefetch();

      // Clear selection if the deleted tenant was selected
      // Use local tenants array which should be updated after refetch
      if (selected === deletingTenant.tenant_id) {
        const remainingTenants = tenants.filter(
          (t: Tenant) => t.tenant_id !== deletingTenant.tenant_id
        );
        if (remainingTenants.length > 0) {
          onSelect(remainingTenants[0].tenant_id);
        } else {
          onSelect("");
        }
      }
    } catch (error: any) {
      const errorMessage = error?.response?.data?.detail || error?.message || "";
      message.error(errorMessage || t("tenantResources.tenantDeleteFailed"));
    } finally {
      setDeleteModalVisible(false);
      setDeletingTenant(null);
      setTenantUsers([]);
    }
  };

  // Close delete modal
  const handleDeleteCancel = () => {
    setDeleteModalVisible(false);
    setDeletingTenant(null);
    setTenantUsers([]);
  };

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields();

      if (editingTenant) {
        await updateTenant(editingTenant.tenant_id, {
          tenant_name: values.name,
        });
        // Refresh the tenant list to reflect the updated tenant name
        await onTenantsRefetch();
        message.success(t("tenantResources.tenants.updated"));
      } else {
        // Create tenant first
        const newTenant = await createTenant({ tenant_name: values.name });
        // Refresh the tenant list to include the new tenant
        await onTenantsRefetch();
        onSelect(newTenant.tenant_id);
        message.success(t("tenantResources.tenants.created"));

        // If generate admin account is enabled, create invitation and register admin
        if (generateAdminAccount && values.adminEmail && values.adminPassword) {
          try {
            // Create invitation code with capacity=1 and code_type=ADMIN_INVITE
            const invitation = await createInvitation({
              tenant_id: newTenant.tenant_id,
              code_type: "ADMIN_INVITE",
              capacity: 1,
            });

            // Register admin account using the invitation code
            const signupResult = await authService.signUp(
              values.adminEmail,
              values.adminPassword,
              invitation.invitation_code
            );

            if (signupResult.error) {
              // Handle signup error
              const errorMsg = signupResult.error.message || "";
              if (errorMsg.includes("already exists") || errorMsg.includes("EMAIL_ALREADY_EXISTS")) {
                message.error(t("tenantResources.tenants.emailAlreadyExists"));
              } else {
                message.error(t("tenantResources.tenants.failedToCreateAdminAccount"));
              }
            } else {
              message.success(t("tenantResources.tenants.adminAccountCreated"));
              // Delete the invitation code after successful admin registration
              try {
                await deleteInvitation(invitation.invitation_code);
              } catch (deleteError) {
                // Log error but don't block the success flow
                console.warn("Failed to delete invitation code after admin registration:", deleteError);
              }
              // Refresh user list and invitation list to show the newly created admin
              onUserListRefresh?.();
              onInvitationListRefresh?.();
            }
          } catch (adminError: any) {
            // Handle admin account creation error
            const errorMsg = adminError?.response?.data?.message || adminError?.message || "";
            if (errorMsg.includes("already exists") || errorMsg.includes("EMAIL_ALREADY_EXISTS")) {
              message.error(t("tenantResources.tenants.emailAlreadyExists"));
            } else {
              message.error(t("tenantResources.tenants.failedToCreateAdminAccount"));
            }
          }
        }
      }
      setModalVisible(false);
    } catch (err: any) {
      const errorMessage = err?.response?.data?.message || err?.message || "";
      const nameConflictMatch = errorMessage.match(/Tenant with name '(.*)' already exists/i);

      if (nameConflictMatch && nameConflictMatch[1]) {
        // Extract the duplicate name and show translated error
        message.error(t("tenantResources.tenants.nameExists", { name: nameConflictMatch[1] }));
      } else if (errorMessage.includes("Tenant name cannot be empty")) {
        // Handle empty name error
        message.error(t("tenantResources.tenants.nameRequired"));
      } else {
        // Show generic error for other cases
        message.error(t("tenantResources.tenantOperationFailed"));
      }
    }
  };

  return (
    <div className="p-2">
      <div className="flex items-center justify-between mb-2 px-1">
        <div className="text-sm font-medium text-gray-600">
          {t("tenantResources.tenants.tenants")}
        </div>
        <Button
          type="text"
          size="small"
          icon={<Plus className="h-3 w-3" />}
          onClick={openCreate}
          className="p-1 hover:bg-gray-100 rounded"
        />
      </div>
      <div
        className="space-y-1 overflow-y-auto"
        style={{ maxHeight: "calc(100vh - 340px)" }}
      >
        {loading && (
          <div key="loading" className="p-4 text-center text-gray-500">
            <Spin size="small" /> Loading tenants...
          </div>
        )}
        {!loading && tenants.length === 0 && (
          <div key="empty" className="p-4 text-center text-gray-500">No tenants found</div>
        )}
        {!loading && tenants.length > 0 && (
          <>
            {tenants.map((tenant, index) => (
            <div
              key={tenant.tenant_id || `tenant-${index}`}
              className={`group p-2 rounded-md cursor-pointer transition-all ${
                selected === tenant.tenant_id
                  ? "bg-blue-50 border border-blue-200"
                  : "hover:bg-gray-50"
              }`}
              onClick={() => onSelect(tenant.tenant_id)}
            >
              <div className="flex items-center justify-between">
                <div className="flex-1">
                  {tenant.tenant_name || t("tenantResources.tenants.unnamed")}
                </div>
                <div className="opacity-0 group-hover:opacity-100 flex space-x-1">
                  <Button
                    type="text"
                    size="small"
                    icon={<Edit className="h-3 w-3" />}
                    onClick={(e) => {
                      e.stopPropagation();
                      openEdit(tenant);
                    }}
                    className="p-1 hover:bg-gray-200 rounded"
                  />
                  {/* Delete button - shows warning modal with users list */}
                  <Button
                    type="text"
                    size="small"
                    icon={<Trash2 className="h-3 w-3" />}
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDeleteClick(tenant);
                    }}
                    className="p-1 hover:bg-red-100 text-red-500 hover:text-red-600 rounded"
                  />
                </div>
              </div>
            </div>
            ))}
          </>
        )}
      </div>

      {/* Pagination */}
      {total !== undefined && total > 0 && (
        <div className="p-2 flex justify-center">
          <Pagination
            current={page}
            pageSize={pageSize}
            total={total}
            onChange={onPageChange}
            showSizeChanger={false}
            size="small"
            hideOnSinglePage={true}
          />
        </div>
      )}

      {/* Tenant Modal */}
      <Modal
        title={
          editingTenant
            ? t("tenantResources.tenants.editTenant")
            : t("tenantResources.tenants.createTenant")
        }
        open={modalVisible}
        onOk={handleSubmit}
        onCancel={() => setModalVisible(false)}
        okText={t("common.confirm")}
        cancelText={t("common.cancel")}
      >
        <Form layout="vertical" form={form} autoComplete="off" style={{ marginBottom: -12 }}>
          <Form.Item
            name="name"
            label={t("tenantResources.tenants.name")}
            rules={[
              {
                required: true,
                message: t("common.required"),
              },
            ]}
          >
            <Input placeholder={t("tenantResources.tenants.namePlaceholder")} />
          </Form.Item>

          {/* Generate Admin Account Switch - Only show in create mode */}
          {!editingTenant && (
            <>
              <Form.Item
                labelCol={{ span: 24 }}
                wrapperCol={{ span: 24 }}
              >
                <div className="flex items-center justify-between">
                  <span>{t("tenantResources.tenants.generateAdminAccount")}</span>
                  <Switch
                    checked={generateAdminAccount}
                    onChange={(checked) => {
                      setGenerateAdminAccount(checked);
                      if (!checked) {
                        form.resetFields(["adminEmail", "adminPassword", "confirmAdminPassword"]);
                      }
                    }}
                  />
                </div>
              </Form.Item>

              {/* Admin account fields - show when switch is enabled */}
              {generateAdminAccount && (
                <>
                  <Form.Item
                    name="adminEmail"
                    label={t("tenantResources.tenants.adminEmail")}
                    rules={[
                      {
                        required: true,
                        message: t("tenantResources.tenants.adminEmailRequired"),
                      },
                      {
                        type: "email",
                        message: t("tenantResources.tenants.invalidEmailFormat"),
                      },
                    ]}
                  >
                    <Input placeholder={t("tenantResources.tenants.adminEmail")} autoComplete="new-email" />
                  </Form.Item>

                  <Form.Item
                    name="adminPassword"
                    label={t("tenantResources.tenants.adminPassword")}
                    rules={[
                      {
                        required: true,
                        message: t("tenantResources.tenants.adminPasswordRequired"),
                      },
                      {
                        min: 6,
                        message: t("tenantResources.tenants.weakPassword"),
                      },
                    ]}
                  >
                    <Input.Password
                      placeholder={t("tenantResources.tenants.adminPassword")}
                      autoComplete="new-password"
                    />
                  </Form.Item>

                  <Form.Item
                    name="confirmAdminPassword"
                    label={t("tenantResources.tenants.confirmAdminPassword")}
                    dependencies={["adminPassword"]}
                    rules={[
                      {
                        required: true,
                        message: t("tenantResources.tenants.adminPasswordRequired"),
                      },
                      ({ getFieldValue }) => ({
                        validator(_, value) {
                          if (!value || getFieldValue("adminPassword") === value) {
                            return Promise.resolve();
                          }
                          return Promise.reject(new Error(t("tenantResources.tenants.passwordsDoNotMatch")));
                        },
                      }),
                    ]}
                  >
                    <Input.Password
                      placeholder={t("tenantResources.tenants.confirmAdminPassword")}
                      autoComplete="new-password"
                    />
                  </Form.Item>
                </>
              )}
            </>
          )}
        </Form>
      </Modal>

      {/* Delete Tenant Warning Modal */}
      <Modal
        centered
        title={
          <Space className="text-red-600">
            <AlertTriangle className="h-5 w-5" />
            <span>{t("tenantResources.tenants.deleteTenant")}</span>
          </Space>
        }
        open={deleteModalVisible}
        onOk={handleDeleteConfirm}
        onCancel={handleDeleteCancel}
        okText={t("common.confirm")}
        cancelText={t("common.cancel")}
        okButtonProps={{ danger: true }}
        confirmLoading={deleteLoading}
        width={500}
      >
        <Alert
          type="error"
          showIcon
          className="mb-4"
          message={t("common.cannotBeUndone")}
          description={
            <ul className="list-disc pl-4 mt-2 space-y-1">
              <li>
                {t("tenantResources.tenants.willBeDeleted", {
                  name: deletingTenant?.tenant_name,
                })}
              </li>
              <li>{t("tenantResources.tenants.resourcesWillBeDeleted")}</li>
            </ul>
          }
        />

        {/* Users list */}
        {deleteLoading ? (
          <Spin size="small" />
        ) : tenantUsers.length > 0 ? (
          <div className="mt-4">
            <div className="font-medium text-gray-700 dark:text-gray-300 mb-2">
              {t("tenantResources.tenants.usersToBeDeleted", {
                count: tenantUsers.length,
              })}
            </div>
            <div className="max-h-32 overflow-y-auto border rounded-md">
              <table className="min-w-full text-sm">
                <thead className="bg-gray-50 dark:bg-gray-800 sticky top-0">
                  <tr>
                    <th className="px-3 py-1.5 text-left text-gray-500 dark:text-gray-400 text-xs font-normal">
                      {t("tenantResources.users.email")}
                    </th>
                    <th className="px-3 py-1.5 text-left text-gray-500 dark:text-gray-400 text-xs font-normal">
                      {t("tenantResources.users.role")}
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                  {tenantUsers.slice(0, 5).map((user: any, idx: number) => (
                    <tr
                      key={user.id || idx}
                      className="hover:bg-gray-50 dark:hover:bg-gray-800"
                    >
                      <td className="px-3 py-1.5 text-gray-900 dark:text-gray-100 text-sm">
                        {user.username || "-"}
                      </td>
                      <td className="px-3 py-1.5 text-gray-900 dark:text-gray-100 text-sm">
                        {t(`user.role.${user.role?.toLowerCase()}`) || "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {tenantUsers.length > 5 && (
                <div className="px-3 py-1.5 text-xs text-gray-500 bg-gray-50 dark:bg-gray-800">
                  ...and {tenantUsers.length - 5} more
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="mt-4 text-gray-500 text-sm">
            {t("tenantResources.tenants.noUsers")}
          </div>
        )}
      </Modal>
    </div>
  );
}

export default function UserManageComp() {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const { user } = useAuthorizationContext();
  const { isSpeedMode } = useDeployment();

  // Check if user is super admin (speed mode or admin role)
  const isSuperAdmin = isSpeedMode || user?.role === USER_ROLES.SU;

  // Pagination state
  const [currentPage, setCurrentPage] = useState(1);

  // Get paginated tenant data from API
  const {
    data: tenantData,
    isLoading: tenantsLoading,
    refetch: refetchTenants,
  } = useTenantList({ page: currentPage, page_size: DEFAULT_PAGE_SIZE });

  // For non-super admins, automatically select their own tenant based on user.tenantId
  // This must be declared before useQuery that uses tenantId
  const [tenantId, setTenantId] = useState<string | null>(null);
  useEffect(() => {
    if (!isSuperAdmin && user?.tenantId && !tenantId) {
      setTenantId(user.tenantId);
    }
  }, [isSuperAdmin, tenantId, user?.tenantId]);

  // For non-super-admin users, directly fetch their tenant details
  // This ensures they always get the correct tenant info regardless of pagination
  const {
    data: directTenantData,
    isLoading: directTenantLoading,
    refetch: refetchDirectTenant,
  } = useQuery({
    queryKey: ["tenant", tenantId],
    queryFn: async () => {
      if (!tenantId || isSuperAdmin) return null;
      return await getTenant(tenantId);
    },
    enabled: !!tenantId && !isSuperAdmin,
    staleTime: 1000 * 60, // Cache for 1 minute
  });

  // Handle page change
  const handlePageChange = (page: number) => {
    setCurrentPage(page);
  };

  // Reset tenants when page changes to super admin
  useEffect(() => {
    if (isSuperAdmin) {
      setCurrentPage(1);
    }
  }, [isSuperAdmin]);

  // Tenant management state for super admin operations
  const [tenantsState, setTenantsState] = useState<Tenant[]>([]);

  // User list refresh key - increment to trigger user list refetch
  const [userListRefreshKey, setUserListRefreshKey] = useState(0);

  // Invitation list refresh key - increment to trigger invitation list refetch
  const [invitationListRefreshKey, setInvitationListRefreshKey] = useState(0);

  // Get current tenant name
  // For non-super-admin: use directly fetched tenant data (directTenantData)
  // For super-admin: use paginated tenant list (tenantData)
  let currentTenant: Tenant | undefined;
  let currentTenantName: string;
  
  if (!isSuperAdmin && directTenantData) {
    // Non-super-admin: use directly fetched tenant info
    currentTenant = directTenantData;
    currentTenantName = directTenantData.tenant_name || t("tenantResources.tenants.unnamed");
  } else {
    // Super-admin: search in paginated list
    currentTenant = tenantData?.data?.find((t: Tenant) => t.tenant_id === tenantId);
    currentTenantName = currentTenant?.tenant_name || t("tenantResources.tenants.unnamed");
  }

  // Tenant name editing states
  const [isEditingTenantName, setIsEditingTenantName] = useState(false);
  const [editingTenantName, setEditingTenantName] = useState("");
  const tenantNameInputRef = useRef<any>(null);

  // Start editing tenant name
  const startEditingTenantName = () => {
    if (!tenantId) return;
    setEditingTenantName(currentTenantName);
    setIsEditingTenantName(true);
    // Focus input after render
    setTimeout(() => {
      tenantNameInputRef.current?.focus();
    }, 0);
  };

  // Save tenant name
  const saveTenantName = async () => {
    if (!tenantId) return;
    const trimmedName = editingTenantName.trim();
    if (!trimmedName) {
      message.error(t("tenantResources.tenants.nameRequired"));
      return;
    }
    if (trimmedName === currentTenantName) {
      setIsEditingTenantName(false);
      return;
    }
    try {
      await updateTenant(tenantId, { tenant_name: trimmedName });
      // For non-super-admin, refetch the direct tenant data; for super-admin, refetch the list
      if (!isSuperAdmin) {
        await refetchDirectTenant();
      } else {
        await refetchTenants();
      }
      message.success(t("tenantResources.tenants.updated"));
      setIsEditingTenantName(false);
    } catch (error) {
      message.error(t("tenantResources.tenantOperationFailed"));
    }
  };

  // Cancel editing tenant name
  const cancelEditingTenantName = () => {
    setEditingTenantName("");
    setIsEditingTenantName(false);
  };

  // Handle input key events
  const handleTenantNameKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      saveTenantName();
    } else if (e.key === "Escape") {
      cancelEditingTenantName();
    }
  };

  return (
    <div className="w-full h-full">
      {/* Page header: grouped header without dividing line */}
      <div className="w-full px-10 pt-10">
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35 }}
        >
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-full bg-gradient-to-br from-purple-500 to-indigo-500 flex items-center justify-center shadow-sm">
              <Building2 className="h-6 w-6 text-white" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-purple-600 dark:text-purple-500">
                {t("tenantResources.title") || "Tenant Resource Management"}
              </h1>
              <p className="text-slate-600 dark:text-slate-300 mt-1">
                {t("tenantResources.subtitle") ||
                  "Manage tenants, users, groups and resources"}
              </p>
            </div>
          </div>
        </motion.div>
      </div>
      <Row className="flex-1 min-h-0 h-full" align="stretch">
        <Can permission="tenant.list:read">
          <Col className="flex flex-col h-full" style={{ width: 300 }}>
            <div className="h-full pr-6">
              <div className="sticky top-6">
                <div className="bg-white dark:bg-gray-800 rounded-md shadow-sm p-3">
                  <TenantList
                    selected={tenantId}
                    onSelect={(id) => setTenantId(id)}
                    tenants={tenantData?.data || []}
                    total={tenantData?.total}
                    page={tenantData?.page}
                    pageSize={tenantData?.page_size}
                    totalPages={tenantData?.total_pages}
                    onPageChange={handlePageChange}
                    onTenantsRefetch={async () => {
                      setCurrentPage(1);
                      return refetchTenants();
                    }}
                    loading={tenantsLoading}
                    t={t}
                    onUserListRefresh={() => setUserListRefreshKey((prev) => prev + 1)}
                    onInvitationListRefresh={() => setInvitationListRefreshKey((prev) => prev + 1)}
                  />
                </div>
              </div>
            </div>
          </Col>
        </Can>
        <Col className="flex-1 flex flex-col p-6 overflow-hidden">
          <div className="bg-white dark:bg-gray-800 rounded-md shadow-sm p-4 h-full flex flex-col overflow-hidden">
            {/* Tenant name header */}
            <div className="mb-4 pb-2 border-b border-gray-200 dark:border-gray-700 flex-shrink-0">
              {isEditingTenantName ? (
                <Input
                  ref={tenantNameInputRef}
                  value={editingTenantName}
                  onChange={(e) => setEditingTenantName(e.target.value)}
                  onBlur={saveTenantName}
                  onKeyDown={handleTenantNameKeyDown}
                  className="text-lg font-semibold text-gray-900 dark:text-gray-100"
                  placeholder={t("tenantResources.tenants.name")}
                />
              ) : (
                <div
                  className="flex items-center gap-2 group cursor-pointer"
                  onClick={startEditingTenantName}
                >
                  <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                    {currentTenantName}
                  </h2>
                  <Edit2 className="h-4 w-4 text-gray-400 opacity-0 group-hover:opacity-100 transition-opacity" />
                </div>
              )}
            </div>

            {tenantId ? (
              <Tabs
                defaultActiveKey="users"
                className="h-full flex flex-col"
                items={[
                  {
                    key: "users",
                    label: t("tenantResources.tabs.users") || "Users",
                    children: <UserList tenantId={tenantId} refreshKey={userListRefreshKey} />,
                  },
                  {
                    key: "groups",
                    label: t("tenantResources.tabs.groups") || "Groups",
                    children: <GroupList tenantId={tenantId} />,
                  },
                  {
                    key: "models",
                    label: t("tenantResources.tabs.models") || "Models",
                    children: <ModelList tenantId={tenantId} />,
                  },
                  {
                    key: "knowledge",
                    label:
                      t("tenantResources.tabs.knowledge") || "Knowledge Base",
                    children: <KnowledgeList tenantId={tenantId} />,
                  },
                  {
                          key: "agents",
                          label: t("tenantResources.tabs.agents") || "Agents",
                          children: <AgentList tenantId={tenantId} />,
                  },
                  {
                    key: "mcp",
                    label: t("tenantResources.tabs.mcp") || "MCP",
                    children: <McpList tenantId={tenantId} />,
                  },
                  {
                    key: "invitations",
                    label: t("tenantResources.invitation.tab") || "Invitations",
                    children: <InvitationList tenantId={tenantId} refreshKey={invitationListRefreshKey} />,
                  },
                ]}
              />
            ) : (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <div className="w-16 h-16 bg-gray-100 dark:bg-gray-700 rounded-full flex items-center justify-center mb-4">
                  <Users className="h-8 w-8 text-gray-400" />
                </div>
                  <h3 className="text-lg font-medium text-gray-900 dark:text-gray-100">
                  {t("tenantResources.selectTenantFirst") ||
                    "Please select a tenant"}
                </h3>
                <p className="text-gray-500 dark:text-gray-400 max-w-sm">
                  {t("tenantResources.selectTenantDescription") ||
                    "Choose a tenant from the list to manage its users, groups, models, and knowledge base."}
                </p>
              </div>
            )}
          </div>
        </Col>
      </Row>
    </div>
  );
}

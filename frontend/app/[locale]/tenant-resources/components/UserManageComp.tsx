"use client";

import React, { useState } from "react";
import {
  Row,
  Col,
  Tabs,
  Button,
  App,
  Modal,
  Form,
  Input,
  Popconfirm,
  message,
} from "antd";
import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { Users, Plus, Edit, Trash2, Building2 } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { useTenantList } from "@/hooks/tenant/useTenantList";
import {
  type Tenant,
  createTenant,
  updateTenant,
  deleteTenant,
} from "@/services/tenantService";
import UserList from "./resources/UserList";
import GroupList from "./resources/GroupList";
import ModelList from "./resources/ModelList";
import KnowledgeList from "./resources/KnowledgeList";
import InvitationList from "./resources/InvitationList";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { USER_ROLES } from "@/const/modelConfig";

// Removed mockTenants - now using real data from API

function TenantList({
  selected,
  onSelect,
  tenants,
  onTenantsChange,
  onTenantsRefetch,
  loading,
  t,
}: {
  selected: string | null;
  onSelect: (id: string) => void;
  tenants: Tenant[];
  onTenantsChange: (tenants: Tenant[]) => void;
  onTenantsRefetch: () => void;
  loading?: boolean;
  t: (key: string, options?: any) => string;
}) {
  const [editingTenant, setEditingTenant] = useState<Tenant | null>(null);
  const [modalVisible, setModalVisible] = useState(false);
  const [form] = Form.useForm();

  const openCreate = () => {
    setEditingTenant(null);
    form.resetFields();
    setModalVisible(true);
  };

  const openEdit = (tenant: Tenant) => {
    setEditingTenant(tenant);
    form.setFieldsValue({ name: tenant.tenant_name });
    setModalVisible(true);
  };

  const handleDelete = async (tenantId: string) => {
    try {
      await deleteTenant(tenantId);
      message.success(t("tenantResources.tenants.deleted"));
      const newTenants = tenants.filter((t) => t.tenant_id !== tenantId);
      onTenantsChange(newTenants);

      if (selected === tenantId && newTenants.length > 0) {
        onSelect(newTenants[0].tenant_id);
      }
    } catch (error) {
      message.error(t("tenantResources.tenantDeleteFailed"));
    }
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
        const newTenant = await createTenant({ tenant_name: values.name });
        // Refresh the tenant list to include the new tenant
        await onTenantsRefetch();
        onSelect(newTenant.tenant_id);
        message.success(t("tenantResources.tenants.created"));
      }
      setModalVisible(false);
    } catch (err) {
      message.error(t("tenantResources.tenantOperationFailed"));
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
      <div className="space-y-1">
        {loading ? (
          <div className="p-4 text-center text-gray-500">
            Loading tenants...
          </div>
        ) : tenants.length === 0 ? (
          <div className="p-4 text-center text-gray-500">No tenants found</div>
        ) : (
          tenants.map((tenant) => (
            <div
              key={tenant.tenant_id}
              className={`group p-2 rounded-md cursor-pointer transition-all ${
                selected === tenant.tenant_id
                  ? "bg-blue-50 border border-blue-200"
                  : "hover:bg-gray-50"
              }`}
            >
              <div className="flex items-center justify-between">
                <div
                  className="flex-1"
                  onClick={() => onSelect(tenant.tenant_id)}
                >
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
                  <Popconfirm
                    title={t("tenantResources.tenants.confirmDelete", {
                      name: tenant.tenant_name,
                    })}
                    description="This action cannot be undone."
                    onConfirm={(e) => {
                      e?.stopPropagation();
                      handleDelete(tenant.tenant_id);
                    }}
                    onCancel={(e) => e?.stopPropagation()}
                  >
                    <Button
                      type="text"
                      size="small"
                      icon={<Trash2 className="h-3 w-3" />}
                      onClick={(e) => e.stopPropagation()}
                      className="p-1 hover:bg-red-100 text-red-500 hover:text-red-600 rounded"
                    />
                  </Popconfirm>
                </div>
              </div>
            </div>
          ))
        )}
      </div>

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
      >
        <Form layout="vertical" form={form}>
          <Form.Item
            name="name"
            label={t("tenantResources.tenants.name")}
            rules={[
              {
                required: true,
                message: t("common.required") || "Please enter tenant name",
              },
            ]}
          >
            <Input placeholder="Enter tenant name" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

export default function UserManageComp() {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const { isSpeedMode } = useDeployment();
  const { user } = useAuth()

  // Check if user is super admin (speed mode or admin role)
  const isSuperAdmin = isSpeedMode || user?.role === USER_ROLES.ADMIN;

  // Get real tenant data from API
  const {
    data: tenantData,
    isLoading: tenantsLoading,
    refetch: refetchTenants,
  } = useTenantList();
  const tenants = tenantData || [];

  // Tenant management state for super admin operations
  const [tenantsState, setTenantsState] = useState<Tenant[]>([]);

  // For non-super admins, use their current tenant (from user metadata or default)
  const [tenantId, setTenantId] = useState<string | null>(
    isSuperAdmin ? tenants[0]?.tenant_id : "default"
  );

  // Get current tenant name
  const currentTenant = tenants.find((t) => t.tenant_id === tenantId);
  const currentTenantName =
    currentTenant?.tenant_name || t("tenantResources.tenants.unnamed");

  return (
    <div className="w-full h-full">
      {/* Page header: grouped header without dividing line */}
      <div className="w-full px-4 md:px-8 lg:px-16 py-6">
        <div className="max-w-7xl mx-auto">
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
      </div>
      {isSuperAdmin ? (
        // Super admin layout: tenant list + resource tabs
        <Row className="h-full">
          <Col className="h-full" style={{ width: 300 }}>
            <div className="h-full pr-6">
              <div className="sticky top-6">
                <div className="bg-white dark:bg-gray-800 rounded-md shadow-sm p-3">
                  <TenantList
                    selected={tenantId}
                    onSelect={(id) => setTenantId(id)}
                    tenants={tenants}
                    onTenantsChange={setTenantsState}
                    onTenantsRefetch={refetchTenants}
                    loading={tenantsLoading}
                    t={t}
                  />
                </div>
              </div>
            </div>
          </Col>
          <Col className="flex-1 p-6">
            <div className="bg-white dark:bg-gray-800 rounded-md shadow-sm p-4 min-h-[300px]">
              {/* Tenant name header */}
              <div className="mb-4 pb-2 border-b border-gray-200 dark:border-gray-700">
                <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                  {currentTenantName}
                </h2>
              </div>

              {tenantId ? (
                <Tabs
                  defaultActiveKey="users"
                  items={[
                    {
                      key: "users",
                      label: t("tenantResources.tabs.users") || "Users",
                      children: <UserList tenantId={tenantId} />,
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
                      key: "invitations",
                      label: t("tenantResources.invitation.tab") || "Invitations",
                      children: <InvitationList tenantId={tenantId} />,
                    },
                  ]}
                />
              ) : (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <div className="w-16 h-16 bg-gray-100 dark:bg-gray-700 rounded-full flex items-center justify-center mb-4">
                    <Users className="h-8 w-8 text-gray-400" />
                  </div>
                  <h3 className="text-lg font-medium text-gray-900 dark:text-gray-100 mb-2">
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
      ) : (
        // Regular user layout: only resource tabs (no tenant selection)
        <div className="h-full p-6">
          <div className="bg-white dark:bg-gray-800 rounded-md shadow-sm p-4 min-h-[300px]">
            {/* Tenant name header */}
            <div className="mb-4 pb-2 border-b border-gray-200 dark:border-gray-700">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                {currentTenantName}
              </h2>
            </div>

            {tenantId ? (
              <Tabs
                defaultActiveKey="users"
                items={[
                  {
                    key: "users",
                    label: t("tenantResources.tabs.users") || "Users",
                    children: <UserList tenantId={tenantId} />,
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
                    key: "invitations",
                    label: t("tenantResources.invitation.tab") || "Invitations",
                    children: <InvitationList tenantId={tenantId} />,
                  },
                ]}
              />
            ) : (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <div className="w-16 h-16 bg-gray-100 dark:bg-gray-700 rounded-full flex items-center justify-center mb-4">
                  <Users className="h-8 w-8 text-gray-400" />
                </div>
                <h3 className="text-lg font-medium text-gray-900 dark:text-gray-100 mb-2">
                  {t("tenantResources.noTenantAssigned") ||
                    "No tenant assigned"}
                </h3>
                <p className="text-gray-500 dark:text-gray-400 max-w-sm">
                  {t("tenantResources.contactAdmin") ||
                    "Please contact your administrator to assign a tenant."}
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

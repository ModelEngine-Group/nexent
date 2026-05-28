"use client";

import React, { useState, useEffect, useRef } from "react";
import { useParams } from "next/navigation";
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
import {
  Users,
  Plus,
  Edit,
  Edit2,
  Building2,
  Trash2,
  AlertTriangle,
  CircleCheckBig,
  CircleOff,
  CircleDot,
  LoaderCircle,
} from "lucide-react";
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
import {
  createInvitation,
  deleteInvitation,
} from "@/services/invitationService";
import { authService } from "@/services/authService";
import { fetchOfficialSkillsWithStatus } from "@/services/skillService";
import { InstallableSkill } from "@/types/agentConfig";
import UserList from "./resources/UserList";
import GroupList from "./resources/GroupList";
import ModelList from "./resources/ModelList";
import KnowledgeList from "./resources/KnowledgeList";
import InvitationList from "./resources/InvitationList";
import AgentList from "./resources/AgentList";
import McpList from "./resources/McpList";
import SkillList from "./resources/SkillList";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { USER_ROLES } from "@/const/auth";
import { Can } from "@/components/permission/Can";
import { Tooltip } from "@/components/ui/tooltip";
import {
  getPasswordChecks,
  getStrengthLevel,
  validatePassword as validatePasswordUtil,
} from "@/lib/utils";

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
  locale,
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
  locale?: string;
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

  // State for auto-install official skills feature
  const [installOfficialSkills, setInstallOfficialSkills] = useState(false);
  const [installableSkills, setInstallableSkills] = useState<
    InstallableSkill[]
  >([]);
  const [selectedSkillIds, setSelectedSkillIds] = useState<Set<string>>(
    new Set()
  );
  const [skillsLoading, setSkillsLoading] = useState(false);
  // Tracks which skills are currently being installed (per-skill async flow)
  const [installingSkills, setInstallingSkills] = useState<Set<string>>(
    new Set()
  );
  // Tracks which skills have completed installation in the current session
  const [installedSkills, setInstalledSkills] = useState<Set<string>>(
    new Set()
  );

  // Password validation state for admin account
  const [adminPasswordValue, setAdminPasswordValue] = useState("");
  const [adminPasswordError, setAdminPasswordError] = useState<{
    target: "adminPassword" | "confirmAdminPassword" | "";
    message: string;
  }>({ target: "", message: "" });

  // Fetch official skills when install switch is toggled on
  useEffect(() => {
    if (!installOfficialSkills) return;

    let cancelled = false;
    setSkillsLoading(true);
    fetchOfficialSkillsWithStatus()
      .then((skills) => {
        if (cancelled) return;
        setInstallableSkills(skills);
        // Pre-select all installable skills by default
        const installableNames = new Set<string>();
        skills.forEach((s) => {
          if (s.status === "installable") {
            installableNames.add(s.name);
          }
        });
        setSelectedSkillIds(installableNames);
      })
      .catch(() => {
        if (!cancelled) {
          message.error("Failed to load official skills");
        }
      })
      .finally(() => {
        if (!cancelled) setSkillsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [installOfficialSkills]);

  const openCreate = () => {
    setEditingTenant(null);
    form.resetFields();
    setGenerateAdminAccount(false);
    setInstallOfficialSkills(false);
    setInstallableSkills([]);
    setSelectedSkillIds(new Set<string>());
    setInstallingSkills(new Set<string>());
    setInstalledSkills(new Set<string>());
    setAdminPasswordValue("");
    setAdminPasswordError({ target: "", message: "" });
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
      const errorMessage =
        error?.response?.data?.detail || error?.message || "";
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

  // Handle admin password input change
  const handleAdminPasswordChange = (
    e: React.ChangeEvent<HTMLInputElement>
  ) => {
    const value = e.target.value;
    setAdminPasswordValue(value);

    if (value && !validatePasswordUtil(value)) {
      setAdminPasswordError({
        target: "adminPassword",
        message:
          t("auth.passwordStrengthError") ||
          "Password must contain uppercase, lowercase, and digit",
      });
      return;
    }

    setAdminPasswordError({ target: "", message: "" });
    const confirmPassword = form.getFieldValue("confirmAdminPassword");
    if (confirmPassword && confirmPassword !== value) {
      setAdminPasswordError({
        target: "confirmAdminPassword",
        message: t("auth.passwordsDoNotMatch"),
      });
    }
  };

  // Handle confirm admin password input change
  const handleConfirmAdminPasswordChange = (
    e: React.ChangeEvent<HTMLInputElement>
  ) => {
    const value = e.target.value;
    const password = form.getFieldValue("adminPassword");

    if (password && !validatePasswordUtil(password)) {
      setAdminPasswordError({
        target: "adminPassword",
        message:
          t("auth.passwordStrengthError") ||
          "Password must contain uppercase, lowercase, and digit",
      });
      return;
    }

    if (value && value !== password) {
      setAdminPasswordError({
        target: "confirmAdminPassword",
        message: t("auth.passwordsDoNotMatch"),
      });
    } else {
      setAdminPasswordError({ target: "", message: "" });
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
        // Build skill_names list from selected skill names for backend ZIP-based installation
        const skillNamesToInstall =
          installOfficialSkills && selectedSkillIds.size > 0
            ? Array.from(selectedSkillIds)
            : undefined;

        // Create tenant (skills are installed via ZIP upload inside the backend)
        const newTenant = await createTenant({
          tenant_name: values.name,
          skill_names: skillNamesToInstall,
          locale,
        });
        // Refresh the tenant list to include the new tenant
        await onTenantsRefetch();
        onSelect(newTenant.tenant_id);
        message.success(t("tenantResources.tenants.created"));

        // Trigger per-skill async tracking: mark all selected skills as "installing"
        // so the UI shows the loader-circle immediately. As each skill resolves
        // (already installed by backend or tracked here), it moves to "installed".
        if (installOfficialSkills && selectedSkillIds.size > 0) {
          const selectedNames = Array.from(selectedSkillIds);
          setInstallingSkills(new Set(selectedNames));
          // The backend has already installed the skills synchronously.
          // For UX, transition each skill to "installed" after a short delay
          // so the user sees the full flow: installable -> installing -> installed.
          selectedNames.forEach((name) => {
            setTimeout(() => {
              setInstallingSkills((prev) => {
                const next = new Set(prev);
                next.delete(name);
                return next;
              });
              setInstalledSkills((prev) => {
                const next = new Set(prev);
                next.add(name);
                return next;
              });
            }, 300);
          });
        }

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
            // Do not auto-login for tenant admin creation
            const signupResult = await authService.signUp(
              values.adminEmail,
              values.adminPassword,
              invitation.invitation_code,
              false
            );

            if (signupResult.error) {
              // Handle signup error
              const errorMsg = signupResult.error.message || "";
              if (
                errorMsg.includes("already exists") ||
                errorMsg.includes("EMAIL_ALREADY_EXISTS")
              ) {
                message.error(t("tenantResources.tenants.emailAlreadyExists"));
              } else {
                message.error(
                  t("tenantResources.tenants.failedToCreateAdminAccount")
                );
              }
            } else {
              message.success(t("tenantResources.tenants.adminAccountCreated"));
              // Delete the invitation code after successful admin registration
              try {
                await deleteInvitation(invitation.invitation_code);
              } catch (deleteError) {
                // Log error but don't block the success flow
                console.warn(
                  "Failed to delete invitation code after admin registration:",
                  deleteError
                );
              }
              // Refresh user list and invitation list to show the newly created admin
              onUserListRefresh?.();
              onInvitationListRefresh?.();
            }
          } catch (adminError: any) {
            // Handle admin account creation error
            const errorMsg =
              adminError?.response?.data?.message || adminError?.message || "";
            if (
              errorMsg.includes("already exists") ||
              errorMsg.includes("EMAIL_ALREADY_EXISTS")
            ) {
              message.error(t("tenantResources.tenants.emailAlreadyExists"));
            } else {
              message.error(
                t("tenantResources.tenants.failedToCreateAdminAccount")
              );
            }
          }
        }
      }
      setModalVisible(false);
    } catch (err: any) {
      const errorMessage = err?.response?.data?.message || err?.message || "";
      const nameConflictMatch = errorMessage.match(
        /Tenant with name '(.*)' already exists/i
      );

      if (nameConflictMatch && nameConflictMatch[1]) {
        // Extract the duplicate name and show translated error
        message.error(
          t("tenantResources.tenants.nameExists", {
            name: nameConflictMatch[1],
          })
        );
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
          <div key="empty" className="p-4 text-center text-gray-500">
            No tenants found
          </div>
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
        <Form
          layout="vertical"
          form={form}
          autoComplete="off"
          style={{ marginBottom: -12 }}
        >
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
              <Form.Item labelCol={{ span: 24 }} wrapperCol={{ span: 24 }}>
                <div className="flex items-center justify-between">
                  <span>
                    {t("tenantResources.tenants.generateAdminAccount")}
                  </span>
                  <Switch
                    checked={generateAdminAccount}
                    onChange={(checked) => {
                      setGenerateAdminAccount(checked);
                      if (!checked) {
                        form.resetFields([
                          "adminEmail",
                          "adminPassword",
                          "confirmAdminPassword",
                        ]);
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
                        message: t(
                          "tenantResources.tenants.adminEmailRequired"
                        ),
                      },
                      {
                        type: "email",
                        message: t(
                          "tenantResources.tenants.invalidEmailFormat"
                        ),
                      },
                    ]}
                  >
                    <Input
                      placeholder={t("tenantResources.tenants.adminEmail")}
                      autoComplete="new-email"
                    />
                  </Form.Item>

                  <Form.Item
                    name="adminPassword"
                    label={t("tenantResources.tenants.adminPassword")}
                    validateStatus={
                      adminPasswordError.target === "adminPassword"
                        ? "error"
                        : ""
                    }
                    help={
                      form.getFieldError("adminPassword").length
                        ? undefined
                        : adminPasswordError.target === "adminPassword"
                          ? adminPasswordError.message
                          : undefined
                    }
                    rules={[
                      {
                        required: true,
                        message: t(
                          "tenantResources.tenants.adminPasswordRequired"
                        ),
                      },
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
                      placeholder={t("tenantResources.tenants.adminPassword")}
                      autoComplete="new-password"
                      onChange={handleAdminPasswordChange}
                    />
                  </Form.Item>

                  {/* Password Strength Indicator */}
                  {adminPasswordValue &&
                    generateAdminAccount &&
                    (() => {
                      const checks = getPasswordChecks(adminPasswordValue);
                      const levelInfo = getStrengthLevel(adminPasswordValue, t);
                      return (
                        <div className="mb-4">
                          <div className="flex items-center justify-between mb-1">
                            <span className="text-xs text-gray-500">
                              {t("auth.passwordStrength") ||
                                "Password strength"}
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
                                    level <= levelInfo.level
                                      ? levelInfo.color
                                      : "#e5e7eb",
                                }}
                              />
                            ))}
                          </div>
                        </div>
                      );
                    })()}

                  <Form.Item
                    name="confirmAdminPassword"
                    label={t("tenantResources.tenants.confirmAdminPassword")}
                    validateStatus={
                      adminPasswordError.target === "confirmAdminPassword"
                        ? "error"
                        : ""
                    }
                    help={
                      form.getFieldError("confirmAdminPassword").length
                        ? undefined
                        : adminPasswordError.target === "confirmAdminPassword"
                          ? adminPasswordError.message
                          : undefined
                    }
                    dependencies={["adminPassword"]}
                    rules={[
                      {
                        required: true,
                        message: t(
                          "tenantResources.tenants.adminPasswordRequired"
                        ),
                      },
                      ({ getFieldValue }) => ({
                        validator(_, value) {
                          const password = getFieldValue("adminPassword");
                          if (password && !validatePasswordUtil(password)) {
                            setAdminPasswordError({
                              target: "adminPassword",
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
                          if (
                            !value ||
                            getFieldValue("adminPassword") === value
                          ) {
                            return Promise.resolve();
                          }
                          return Promise.reject(
                            new Error(
                              t("tenantResources.tenants.passwordsDoNotMatch")
                            )
                          );
                        },
                      }),
                    ]}
                    hasFeedback
                  >
                    <Input.Password
                      placeholder={t(
                        "tenantResources.tenants.confirmAdminPassword"
                      )}
                      autoComplete="new-password"
                      onChange={handleConfirmAdminPasswordChange}
                    />
                  </Form.Item>
                </>
              )}
            </>
          )}

          {/* Auto-Install Official Skills Switch - Only show in create mode */}
          {!editingTenant && (
            <>
              <Form.Item labelCol={{ span: 24 }} wrapperCol={{ span: 24 }}>
                <div className="flex items-center justify-between">
                  <span>
                    {t("tenantResources.tenants.installOfficialSkills")}
                  </span>
                  <Switch
                    checked={installOfficialSkills}
                    onChange={(checked) => {
                      setInstallOfficialSkills(checked);
                      if (!checked) {
                        setSelectedSkillIds(new Set<string>());
                        setInstallingSkills(new Set<string>());
                        setInstalledSkills(new Set<string>());
                      }
                    }}
                  />
                </div>
              </Form.Item>

              {/* Skill selector - show when switch is enabled */}
              {installOfficialSkills && (
                <div className="mb-4">
                  <div className="text-sm font-medium text-gray-700 mb-2">
                    {t("tenantResources.tenants.selectSkills")}
                  </div>

                  {skillsLoading ? (
                    <div className="flex items-center justify-center py-4">
                      <Spin size="small" />
                      <span className="ml-2 text-gray-500 text-sm">
                        {t("tenantResources.tenants.skillsLoading")}
                      </span>
                    </div>
                  ) : installableSkills.length === 0 ? (
                    <div className="text-gray-500 text-sm py-2">
                      {t("tenantResources.tenants.noSkillsAvailable")}
                    </div>
                  ) : (
                    <div
                      className="border border-gray-200 rounded-md max-h-60 overflow-y-auto"
                      style={{ maxHeight: "240px" }}
                    >
                      {/* Select all */}
                      <div className="flex items-center px-3 py-2 border-b border-gray-200 bg-gray-50">
                        <input
                          type="checkbox"
                          checked={installableSkills.every((s) =>
                            selectedSkillIds.has(s.name)
                          )}
                          onChange={() => {
                            if (
                              installableSkills.every((s) =>
                                selectedSkillIds.has(s.name)
                              )
                            ) {
                              setSelectedSkillIds(new Set<string>());
                            } else {
                              setSelectedSkillIds(
                                new Set(installableSkills.map((s) => s.name))
                              );
                            }
                          }}
                          className="mr-3 w-4 h-4 accent-blue-500 cursor-pointer shrink-0"
                        />
                        <span className="flex-1 text-sm font-medium text-gray-700">
                          {t("common.selectAll") || "Select all"}
                        </span>
                      </div>

                      {installableSkills.map((skill) => {
                        // Determine effective status: installing > installed > original status
                        const isInstalling = installingSkills.has(skill.name);
                        const isInstalledSession = installedSkills.has(
                          skill.name
                        );
                        const isAlreadyInstalled =
                          skill.status === "installed" || isInstalledSession;
                        const isResourceMissing =
                          skill.status === "resource_missing";

                        let iconElement: React.ReactNode;
                        let tooltipText: string;

                        if (isInstalling) {
                          iconElement = (
                            <LoaderCircle className="h-4 w-4 text-gray-400 shrink-0 animate-spin" />
                          );
                          tooltipText = t(
                            "tenantResources.tenants.skillStatus.installing"
                          );
                        } else if (isAlreadyInstalled) {
                          iconElement = (
                            <CircleCheckBig className="h-4 w-4 text-green-500 shrink-0" />
                          );
                          tooltipText = t(
                            "tenantResources.tenants.skillStatus.installed"
                          );
                        } else if (isResourceMissing) {
                          iconElement = (
                            <CircleOff className="h-4 w-4 text-red-400 shrink-0" />
                          );
                          tooltipText = t(
                            "tenantResources.tenants.skillStatus.resourceMissing"
                          );
                        } else {
                          iconElement = (
                            <CircleDot className="h-4 w-4 text-green-500 shrink-0" />
                          );
                          tooltipText = t(
                            "tenantResources.tenants.skillStatus.installable"
                          );
                        }

                        const isDisabled =
                          isAlreadyInstalled || isResourceMissing;

                        return (
                          <div
                            key={skill.skill_id}
                            className={`flex items-center px-3 py-2 border-b border-gray-100 last:border-b-0 hover:bg-gray-50 transition-colors ${
                              isDisabled ? "opacity-50" : ""
                            }`}
                          >
                            <input
                              type="checkbox"
                              checked={selectedSkillIds.has(skill.name)}
                              onChange={() => {
                                if (isInstalling) return;
                                const newSet = new Set(selectedSkillIds);
                                if (newSet.has(skill.name)) {
                                  newSet.delete(skill.name);
                                } else {
                                  newSet.add(skill.name);
                                }
                                setSelectedSkillIds(newSet);
                              }}
                              disabled={
                                isInstalling ||
                                isAlreadyInstalled ||
                                isResourceMissing
                              }
                              className="mr-3 w-4 h-4 accent-blue-500 cursor-pointer shrink-0"
                            />
                            <span className="flex-1 text-sm text-gray-800 truncate">
                              {skill.name}
                            </span>
                            <span className="ml-2 shrink-0">
                              <Tooltip title={tooltipText}>
                                {iconElement}
                              </Tooltip>
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
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
  const params = useParams();
  const locale = (params.locale as string) || "en";

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
    currentTenantName =
      directTenantData.tenant_name || t("tenantResources.tenants.unnamed");
  } else {
    // Super-admin: search in paginated list
    currentTenant = tenantData?.data?.find(
      (t: Tenant) => t.tenant_id === tenantId
    );
    currentTenantName =
      currentTenant?.tenant_name || t("tenantResources.tenants.unnamed");
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
                    onUserListRefresh={() =>
                      setUserListRefreshKey((prev) => prev + 1)
                    }
                    onInvitationListRefresh={() =>
                      setInvitationListRefreshKey((prev) => prev + 1)
                    }
                    locale={locale}
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
                    children: (
                      <UserList
                        tenantId={tenantId}
                        refreshKey={userListRefreshKey}
                      />
                    ),
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
                    key: "skills",
                    label: "Skills",
                    children: <SkillList tenantId={tenantId} />,
                  },
                  {
                    key: "invitations",
                    label: t("tenantResources.invitation.tab") || "Invitations",
                    children: (
                      <InvitationList
                        tenantId={tenantId}
                        refreshKey={invitationListRefreshKey}
                      />
                    ),
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

"use client";

import React, { useState } from "react";
import {
  Button,
  Typography,
  Space,
  Modal,
  Form,
  Input,
  App,
  Flex,
  Alert,
  Tag,
  Tooltip,
} from "antd";
import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import {
  User,
  LogOut,
  Trash2,
  Shield,
  Mail,
  Edit,
  Key,
  AlertTriangle,
  ChevronRight,
} from "lucide-react";
import { USER_ROLES } from "@/const/modelConfig";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useAuthenticationContext } from "@/components/providers/AuthenticationProvider";
import { useGroupList } from "@/hooks/group/useGroupList";
import { useMemo } from "react";

const { Text, Paragraph } = Typography;

/**
 * UserProfileComp - User profile and account settings component
 *
 * Features:
 * - Display user profile information (email, role, etc.)
 * - Edit user profile
 * - Change password
 * - Logout
 * - Delete account (with confirmation)
 */
export default function UserProfileComp() {
  const { t } = useTranslation("common");
  const { message: antdMessage } = App.useApp();
  const { logout, revoke, isLoading } = useAuthenticationContext()
  const { user, groupIds } = useAuthorizationContext()

  // Fetch groups for group name mapping
  const { data: groupData } = useGroupList(user?.tenantId || null, 1, 100);
  const groups = groupData?.groups || [];

  // Create group name mapping from group_id to group_name
  const groupNameMap = useMemo(() => {
    const map = new Map<number, string>();
    groups.forEach((group) => {
      map.set(group.group_id, group.group_name);
    });
    return map;
  }, [groups]);

  // Get user's group names
  const userGroupNames = useMemo(() => {
    if (!groupIds || groupIds.length === 0) return [];
    return groupIds.map((id) => ({
      id,
      name: groupNameMap.get(id) || t("common.unknown"),
      description: groups.find((g) => g.group_id === id)?.group_description || "",
    }));
  }, [groupIds, groupNameMap, groups, t]);

  // Modal states
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [isPasswordModalOpen, setIsPasswordModalOpen] = useState(false);
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);

  // Form instances
  const [editForm] = Form.useForm();
  const [passwordForm] = Form.useForm();

  // Get role display name
  const getRoleDisplayName = (role: string) => {
    switch (role) {
      case USER_ROLES.SPEED:
        return t("auth.speed");
      case USER_ROLES.SU:
        return t("auth.su");
      case USER_ROLES.ADMIN:
        return t("auth.admin");
      case USER_ROLES.DEV:
        return t("auth.dev");
      case USER_ROLES.USER:
        return t("auth.user");
      default:
        return t("auth.user");
    }
  };

  // Handle logout
  const handleLogout = async () => {
    try {
      await logout();
      window.location.href = "/";
    } catch (error) {
      antdMessage.error(t("auth.logoutFailed"));
    }
  };

  // Handle delete account
  const handleDeleteAccount = async () => {
    try {
      await revoke();
      antdMessage.success(t("auth.revokeSuccess"));
      window.location.href = "/";
    } catch (error) {
      antdMessage.error(t("auth.revokeFailed"));
    }
  };

  // Open edit modal
  // const openEditModal = () => {
  //   editForm.setFieldsValue({
  //     email: user?.email || "",
  //     displayName: user?.email?.split("@")[0] || "",
  //   });
  //   setIsEditModalOpen(true);
  // };

  return (
    <Flex vertical className="h-full w-full">
      {/* Page header */}
      <div className="flex-shrink-0 w-full px-4 md:px-8 lg:px-16 py-8">
        <div className="max-w-2xl mx-auto">
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35 }}
          >
            <div className="flex items-center gap-3">
              <div className="w-12 h-12 rounded-full bg-gradient-to-br from-blue-500 to-indigo-500 flex items-center justify-center shadow-sm">
                <User className="h-6 w-6 text-white" />
              </div>
              <div>
                <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">
                  {t("profile.title") || "User Profile"}
                </h1>
                <p className="text-slate-500 dark:text-slate-400 text-sm mt-0.5">
                  {t("profile.subtitle") || "Manage your account settings"}
                </p>
              </div>
            </div>
          </motion.div>
        </div>
      </div>

      {/* Main content area */}
      <div className="flex-1 overflow-auto px-4 md:px-8 lg:px-16 py-2">
        <div className="max-w-2xl mx-auto space-y-4">
          {/* Account Info Section */}
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, delay: 0.1 }}
          >
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-100 dark:border-gray-700 overflow-hidden">
              {/* Header */}
              <div className="px-6 py-4 border-b border-gray-100 dark:border-gray-700 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Mail className="h-5 w-5 text-blue-500" />
                  <span className="font-medium text-gray-900 dark:text-gray-100">
                    {t("profile.profileInfo") || "Account Info"}
                  </span>
                </div>
                <Button
                  type="text"
                  size="small"
                  icon={<Edit className="h-4 w-4" />}
                  disabled
                >
                  {t("common.edit") || "Edit"}
                </Button>
              </div>

              {/* Info Items */}
              <div className="divide-y divide-gray-50 dark:divide-gray-700/50">
                <div className="px-6 py-3 flex items-center justify-between">
                  <span className="text-gray-500 dark:text-gray-400 text-sm">
                    {t("common.email") || "Email"}
                  </span>
                  <span className="text-gray-900 dark:text-gray-100 text-sm font-medium">
                    {user?.email || "-"}
                  </span>
                </div>
                <div className="px-6 py-3 flex items-center justify-between">
                  <span className="text-gray-500 dark:text-gray-400 text-sm">
                    {t("profile.role") || "Role"}
                  </span>
                  <span className="text-gray-900 dark:text-gray-100 text-sm font-medium">
                    {getRoleDisplayName(user?.role || "user")}
                  </span>
                </div>
                <div className="px-6 py-3 flex items-center justify-between">
                  <span className="text-gray-500 dark:text-gray-400 text-sm">
                    {t("agent.userGroup") || "User Group"}
                  </span>
                  <div className="flex flex-wrap gap-1 justify-end max-w-[50%]">
                    {userGroupNames.length > 0 ? (
                      userGroupNames.map((group) => (
                        <Tooltip
                            key={group.id}
                            title={group.description || t("tenantResources.groups.noDescription")}
                          >
                          <Tag
                            color="blue"
                            className="cursor-pointer hover:opacity-80 transition-opacity"
                          >
                            <span className="font-medium">{group.name}</span>
                          </Tag>
                        </Tooltip>
                      ))
                    ) : (
                      <span className="text-gray-400 text-sm">
                        {t("agent.userGroup.empty")}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </motion.div>

          {/* Security Section */}
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, delay: 0.15 }}
          >
            <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-100 dark:border-gray-700 overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-100 dark:border-gray-700 flex items-center gap-2">
                <Shield className="h-5 w-5 text-green-500" />
                <span className="font-medium text-gray-900 dark:text-gray-100">
                  {t("profile.securitySettings") || "Security"}
                </span>
              </div>

              <div className="divide-y divide-gray-50 dark:divide-gray-700/50">
                <div
                  className="w-full px-6 py-3 flex items-center justify-between opacity-50 cursor-not-allowed"
                >
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-blue-50 dark:bg-blue-900/20 flex items-center justify-center">
                      <Edit className="h-4 w-4 text-blue-500" />
                    </div>
                    <div>
                      <div className="text-sm font-medium text-gray-900 dark:text-gray-100">
                        {t("profile.editProfile") || "Edit Profile"}
                      </div>
                      <div className="text-xs text-gray-500 dark:text-gray-400">
                        {t("profile.editProfileDesc") || "Update your account information"}
                      </div>
                    </div>
                  </div>
                  <ChevronRight className="h-4 w-4 text-gray-400" />
                </div>

                <div
                  className="w-full px-6 py-3 flex items-center justify-between opacity-50 cursor-not-allowed"
                >
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-green-50 dark:bg-green-900/20 flex items-center justify-center">
                      <Key className="h-4 w-4 text-green-500" />
                    </div>
                    <div>
                      <div className="text-sm font-medium text-gray-900 dark:text-gray-100">
                        {t("profile.changePassword") || "Change Password"}
                      </div>
                      <div className="text-xs text-gray-500 dark:text-gray-400">
                        {t("profile.passwordDesc") || "Update your password"}
                      </div>
                    </div>
                  </div>
                  <ChevronRight className="h-4 w-4 text-gray-400" />
                </div>

                <button
                  onClick={() => setIsDeleteModalOpen(true)}
                  className="w-full px-6 py-3 flex items-center justify-between hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors text-left"
                >
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-red-50 dark:bg-red-900/20 flex items-center justify-center">
                      <Trash2 className="h-4 w-4 text-red-500" />
                    </div>
                    <div>
                      <div className="text-sm font-medium text-red-600 dark:text-red-400">
                        {t("profile.deleteAccount") || "Delete Account"}
                      </div>
                      <div className="text-xs text-red-400 dark:text-red-500">
                        {t("profile.deleteAccountDesc") || "Permanently delete your account"}
                      </div>
                    </div>
                  </div>
                  <ChevronRight className="h-4 w-4 text-red-400" />
                </button>

                {/* Logout Button - Centered at bottom of Security Section */}
                <div className="px-6 py-3 flex justify-center border-t border-gray-50 dark:border-gray-700/50 mt-2">
                  <Button
                    type="text"
                    danger
                    size="large"
                    icon={<LogOut className="h-4 w-4" />}
                    onClick={handleLogout}
                    loading={isLoading}
                    className="text-gray-500 hover:text-red-500"
                  >
                    <span className="text-sm font-medium">{t("auth.logout") || "Logout"}</span>
                  </Button>
                </div>
              </div>
            </div>
          </motion.div>
        </div>
      </div>

      {/* Edit Profile Modal */}
      <Modal
        title={
          <Space>
            <Edit className="h-5 w-5 text-blue-500" />
            <span>{t("profile.editProfile") || "Edit Profile"}</span>
          </Space>
        }
        open={isEditModalOpen}
        onOk={() => editForm.submit()}
        onCancel={() => setIsEditModalOpen(false)}
        okText={t("common.save") || "Save"}
        cancelText={t("common.cancel") || "Cancel"}
      >
        <Form
          form={editForm}
          layout="vertical"
          onFinish={(values) => {
            antdMessage.success(t("profile.updateSuccess") || "Profile updated successfully");
            setIsEditModalOpen(false);
          }}
        >
          <Form.Item
            name="displayName"
            label={t("profile.displayName") || "Display Name"}
          >
            <Input placeholder={t("profile.enterDisplayName") || "Enter your display name"} />
          </Form.Item>
          <Form.Item
            name="email"
            label={t("common.email") || "Email"}
          >
            <Input disabled placeholder={user?.email} />
          </Form.Item>
        </Form>
      </Modal>

      {/* Change Password Modal */}
      <Modal
        title={
          <Space>
            <Key className="h-5 w-5 text-green-500" />
            <span>{t("profile.changePassword") || "Change Password"}</span>
          </Space>
        }
        open={isPasswordModalOpen}
        onOk={() => passwordForm.submit()}
        onCancel={() => setIsPasswordModalOpen(false)}
        okText={t("common.save") || "Save"}
        cancelText={t("common.cancel") || "Cancel"}
        width={500}
      >
        <Alert
          message={t("profile.passwordAlertTitle") || "Note"}
          description={t("profile.passwordAlertDesc") || "Password change functionality will be available soon."}
          type="info"
          showIcon
          className="mb-4"
        />
        <Form
          form={passwordForm}
          layout="vertical"
          onFinish={(values) => {
            antdMessage.success(t("profile.passwordUpdateSuccess") || "Password updated successfully");
            setIsPasswordModalOpen(false);
            passwordForm.resetFields();
          }}
        >
          <Form.Item
            name="currentPassword"
            label={t("profile.currentPassword") || "Current Password"}
            rules={[{ required: true, message: t("auth.passwordRequired") }]}
          >
            <Input.Password placeholder={t("auth.passwordLabel")} />
          </Form.Item>
          <Form.Item
            name="newPassword"
            label={t("profile.newPassword") || "New Password"}
            rules={[
              { required: true, message: t("auth.passwordRequired") },
              { min: 6, message: t("auth.passwordMinLength") },
            ]}
          >
            <Input.Password placeholder={t("profile.enterNewPassword") || "Enter new password"} />
          </Form.Item>
          <Form.Item
            name="confirmPassword"
            label={t("auth.confirmPasswordLabel") || "Confirm Password"}
            dependencies={["newPassword"]}
            rules={[
              { required: true, message: t("auth.confirmPasswordRequired") },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue("newPassword") === value) {
                    return Promise.resolve();
                  }
                  return Promise.reject(new Error(t("auth.passwordsDoNotMatch")));
                },
              }),
            ]}
          >
            <Input.Password placeholder={t("auth.confirmPasswordLabel")} />
          </Form.Item>
        </Form>
      </Modal>

      {/* Delete Account Confirmation Modal */}
      <Modal
        title={
          <Space className="text-red-600">
            <AlertTriangle className="h-5 w-5" />
            <span>{t("auth.confirmRevoke") || "Confirm Account Deletion"}</span>
          </Space>
        }
        open={isDeleteModalOpen}
        onOk={handleDeleteAccount}
        onCancel={() => setIsDeleteModalOpen(false)}
        okText={t("auth.confirmRevokeOk") || "Delete Anyway"}
        okButtonProps={{ danger: true, loading: isLoading }}
        cancelText={t("auth.cancel") || "Cancel"}
        width={500}
      >
        <Alert
          type="error"
          showIcon
          className="mb-4"
          message={t("profile.deleteWarningTitle") || "This action cannot be undone!"}
          description={
            <ul className="list-disc pl-4 mt-2 space-y-1">
              <li>{t("profile.deleteWarning1") || "Your account will be permanently deleted"}</li>
              <li>{t("profile.deleteWarning2") || "All your conversations and data will be removed"}</li>
              <li>{t("profile.deleteWarning3") || "This action cannot be reversed"}</li>
            </ul>
          }
        />
        <div className="mt-4">
          <Text strong>{t("profile.adminRestrictionTitle") || "Administrator Restriction"}</Text>
          <Paragraph type="secondary" className="mt-1">
            {t("auth.refuseRevokePrompt") || "Your role is tenant administrator. Account deletion for admin is not yet supported."}
          </Paragraph>
        </div>
      </Modal>
    </Flex>
  );
}

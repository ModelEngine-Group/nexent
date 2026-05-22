"use client";

import React, { useState, useEffect } from "react";
import {
  Button,
  Modal,
  App,
  Flex,
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
  ChevronRight,
  KeySquare,
  KeyRound,
  Copy,
} from "lucide-react";
import { USER_ROLES } from "@/const/modelConfig";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useAuthenticationContext } from "@/components/providers/AuthenticationProvider";
import { useGroupList } from "@/hooks/group/useGroupList";
import { useMemo } from "react";
import { DeleteAccountModal } from "@/components/auth/DeleteAccountModal";
import { OAuthAccountsSection } from "@/components/settings/OAuthAccountsSection";
import log from "@/lib/logger";
import {
  getUserTokens,
  deleteUserToken,
  createUserToken,
} from "@/services/tokenService";

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
  const { data: groupData } = useGroupList(user?.tenantId || null);
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
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);

  // AK/SK state
  const [akInfo, setAkInfo] = useState<string | null>(null);
  const [existingTokenIds, setExistingTokenIds] = useState<number[]>([]);
  const [isLoadingAkSk, setIsLoadingAkSk] = useState(false);
  const [isGeneratingAkSk, setIsGeneratingAkSk] = useState(false);

  // Check if user is admin or super admin (cannot delete account)
  const isAdminOrSuperAdmin = user?.role === USER_ROLES.ADMIN || user?.role === USER_ROLES.SU;
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
      case USER_ROLES.ASSET_OWNER:
        return t("auth.assetOwner");
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

  // Fetch AK/SK info on mount
  useEffect(() => {
    const fetchAkSkInfo = async () => {
      if (!user?.id) return;
      setIsLoadingAkSk(true);
      try {
        const tokens = await getUserTokens(user.id);
        if (tokens.length > 0) {
          setAkInfo(tokens[0].access_key);
          setExistingTokenIds(tokens.map((t) => t.token_id));
        }
      } catch (error) {
        log.error("Failed to fetch AK/SK info:", error);
      } finally {
        setIsLoadingAkSk(false);
      }
    };

    fetchAkSkInfo();
  }, [user?.id]);

  // Handle generate AK/SK: delete existing tokens first, then create a new one
  const handleGenerateAkSk = async () => {
    setIsGeneratingAkSk(true);
    try {
      for (const tokenId of existingTokenIds) {
        await deleteUserToken(tokenId);
      }

      const newToken = await createUserToken();
      setAkInfo(newToken.access_key);
      setExistingTokenIds([newToken.token_id]);
      antdMessage.success(t("profile.generateAkSkSuccess") || "Access key generated successfully");
    } catch (error) {
      antdMessage.error(t("profile.generateAkSkFailed") || "Failed to generate access key");
    } finally {
      setIsGeneratingAkSk(false);
    }
  };

  // Handle copy AK to clipboard
  const handleCopyAk = async () => {
    if (akInfo) {
      try {
        await navigator.clipboard.writeText(akInfo);
        antdMessage.success(t("profile.copyAkSuccess") || "Access key copied to clipboard");
      } catch (error) {
        antdMessage.error(t("profile.copyAkFailed") || "Failed to copy access key");
      }
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
                      <KeyRound className="h-4 w-4 text-green-500" />
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

                {/* Generate Access Token Option */}
                <div
                  className="w-full px-6 py-3 flex items-center justify-between hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors cursor-pointer"
                  onClick={() => {
                    if (akInfo) {
                      Modal.confirm({
                        title: t("profile.generateAkSkConfirmTitle") || "Generate New Access Key",
                        content: t("profile.generateAkSkConfirmContent") || "You already have an access key. Generating a new one will overwrite the existing key. Continue?",
                        okText: t("common.confirm") || "Confirm",
                        cancelText: t("common.cancel") || "Cancel",
                        onOk: handleGenerateAkSk,
                        okButtonProps: { loading: isGeneratingAkSk },
                      });
                    } else {
                      handleGenerateAkSk();
                    }
                  }}
                >
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-purple-50 dark:bg-purple-900/20 flex items-center justify-center">
                      <KeySquare className="h-4 w-4 text-purple-500" />
                    </div>
                    <div>
                      <div className="text-sm font-medium text-gray-900 dark:text-gray-100">
                        {t("profile.generateAkSk") || "Generate Access Token"}
                      </div>
                      {akInfo ? (
                        <div className="flex items-center gap-1">
                          <span className="text-xs font-mono text-purple-600 dark:text-purple-400">
                            {akInfo}
                          </span>
                          <Button
                            type="text"
                            size="small"
                            icon={<Copy className="h-3 w-3" />}
                            onClick={(e) => {
                              e.stopPropagation();
                              handleCopyAk();
                            }}
                            className="text-gray-400 hover:text-purple-500 p-0 h-auto"
                          />
                          <Button
                            type="text"
                            size="small"
                            icon={<Trash2 className="h-3 w-3" />}
                            onClick={(e) => {
                              e.stopPropagation();
                              Modal.confirm({
                                title: t("profile.deleteAkSkConfirmTitle") || "Delete Access Key",
                                content: t("profile.deleteAkSkConfirmContent") || "Are you sure you want to delete this access key? This action cannot be undone.",
                                okText: t("common.confirm") || "Confirm",
                                cancelText: t("common.cancel") || "Cancel",
                                okButtonProps: { danger: true },
                                onOk: async () => {
                                  try {
                                    for (const tokenId of existingTokenIds) {
                                      await deleteUserToken(tokenId);
                                    }
                                    setAkInfo(null);
                                    setExistingTokenIds([]);
                                    antdMessage.success(t("profile.deleteAkSkSuccess") || "Access key deleted successfully");
                                  } catch (error) {
                                    antdMessage.error(t("profile.deleteAkSkFailed") || "Failed to delete access key");
                                  }
                                },
                              });
                            }}
                            className="text-gray-400 hover:text-red-500 p-0 h-auto"
                          />
                        </div>
                      ) : (
                        <div className="text-xs text-gray-500 dark:text-gray-400">
                          {t("profile.generateAkSkDesc") || "Create or regenerate your API access key"}
                        </div>
                      )}
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

      {/* Delete Account Confirmation Modal */}
      <DeleteAccountModal
        open={isDeleteModalOpen}
        onOk={handleDeleteAccount}
        onCancel={() => setIsDeleteModalOpen(false)}
        loading={isLoading}
        disabled={isAdminOrSuperAdmin}
      />

      {/* OAuth Linked Accounts */}
      <div className="w-full mt-4">
        <OAuthAccountsSection />
      </div>
    </Flex>
  );
}

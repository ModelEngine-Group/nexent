"use client";

import React from "react";
import { Tabs } from "antd";
import { Building2 } from "lucide-react";
import { motion } from "framer-motion";
import { useTranslation } from "react-i18next";

import { ASSET_OWNER_TENANT_ID } from "@/const/auth";
import UserList from "./resources/UserList";
import ModelList from "./resources/ModelList";
import KnowledgeList from "./resources/KnowledgeList";
import InvitationList from "./resources/InvitationList";
import AgentList from "./resources/AgentList";
import McpList from "./resources/McpList";
import SkillList from "./resources/SkillList";

export default function AssetOwnerResourcesComp() {
  const { t } = useTranslation("common");
  const userListRefreshKey = 0;
  const invitationListRefreshKey = 0;

  return (
    <div className="w-full h-full">
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
                {t("assetOwnerResources.title")}
              </h1>
              <p className="text-slate-600 dark:text-slate-300 mt-1">
                {t("assetOwnerResources.subtitle")}
              </p>
            </div>
          </div>
        </motion.div>
      </div>

      <div className="p-6 h-[calc(100%-7rem)] overflow-hidden">
        <div className="bg-white dark:bg-gray-800 rounded-md shadow-sm p-4 h-full flex flex-col overflow-hidden">
          <div className="mb-4 pb-2 border-b border-gray-200 dark:border-gray-700 flex-shrink-0">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
              {t("assetOwnerResources.tenantName")}
            </h2>
          </div>

          <Tabs
            defaultActiveKey="users"
            className="h-full flex flex-col"
            items={[
              {
                key: "users",
                label: t("tenantResources.tabs.users"),
                children: (
                  <UserList
                    tenantId={ASSET_OWNER_TENANT_ID}
                    refreshKey={userListRefreshKey}
                  />
                ),
              },
              {
                key: "models",
                label: t("tenantResources.tabs.models"),
                children: <ModelList tenantId={ASSET_OWNER_TENANT_ID} />,
              },
              {
                key: "knowledge",
                label: t("tenantResources.tabs.knowledge"),
                children: <KnowledgeList tenantId={ASSET_OWNER_TENANT_ID} />,
              },
              {
                key: "agents",
                label: t("tenantResources.tabs.agents"),
                children: <AgentList tenantId={ASSET_OWNER_TENANT_ID} />,
              },
              {
                key: "mcp",
                label: t("tenantResources.tabs.mcp"),
                children: <McpList tenantId={ASSET_OWNER_TENANT_ID} />,
              },
              {
                key: "skills",
                label: "SKILLS",
                children: <SkillList tenantId={ASSET_OWNER_TENANT_ID} />,
              },
              {
                key: "invitations",
                label: t("tenantResources.invitation.tab"),
                children: (
                  <InvitationList
                    tenantId={ASSET_OWNER_TENANT_ID}
                    refreshKey={invitationListRefreshKey}
                  />
                ),
              },
            ]}
          />
        </div>
      </div>
    </div>
  );
}

"use client";

import React, { useEffect, useState, useCallback } from "react";
import { App, Button, Card, Input, List, Menu, Switch, Tabs } from "antd";
import { motion } from "framer-motion";
import "./memory.css";
import {
  MessageSquarePlus,
  Eraser,
  MessageSquareOff,
  UsersRound,
  UserRound,
  Bot,
  Share2,
  Settings,
  MessageSquareDashed,
  Check,
  X,
} from "lucide-react";
import { useTranslation, Trans } from "react-i18next";

import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { useMemory } from "@/hooks/useMemory";
import { useSetupFlow } from "@/hooks/useSetupFlow";
import { MEMORY_TAB_KEYS, MemoryTabKey } from "@/const/modelConfig";
import {
  MEMORY_SHARE_STRATEGY,
  MemoryShareStrategy,
} from "@/const/memoryConfig";
import { SETUP_PAGE_CONTAINER, STANDARD_CARD } from "@/const/layoutConstants";

import { useConfirmModal } from "@/hooks/useConfirmModal";
import { MemoryMenuList } from "./MemoryMenuList";

/**
 * MemoryContent - Main component for memory management page
 * Redesigned from modal to full-page layout with cards
 */
export default function MemoryContent() {
  const { message } = App.useApp();
  const { t } = useTranslation("common");
  const { user } = useAuthorizationContext();
  const { isSpeedMode } = useDeployment();
  const { confirm } = useConfirmModal();

  // Use custom hook for common setup flow logic
  const { pageVariants, pageTransition } = useSetupFlow();

  // Mock user and tenant IDs (should come from context)
  const currentUserId = "user1";
  const currentTenantId = "tenant1";

  const memory = useMemory({
    visible: true,
    currentUserId,
    currentTenantId,
    message,
  });

  const handleClearConfirm = (groupKey: string, groupTitle: string) => {
    confirm({
      title: t("memoryDeleteModal.title"),
      content: (
        <div className="space-y-4 mt-4">
          <p className="text-base">
            <Trans
              i18nKey="memoryDeleteModal.description"
              values={{ title: groupTitle }}
              components={{ strong: <strong className="font-semibold" /> }}
            />
          </p>
          <p className="text-sm text-gray-500">
            {t("memoryDeleteModal.prompt")}
          </p>
        </div>
      ),
      onOk: () => memory.handleClearMemory(groupKey, groupTitle),
    });
  };

  // Render base settings in a horizontal control bar
  const renderBaseSettings = () => {
    const shareOptionLabels: Record<MemoryShareStrategy, string> = {
      [MEMORY_SHARE_STRATEGY.ALWAYS]: t("memoryManageModal.shareOption.always"),
      [MEMORY_SHARE_STRATEGY.ASK]: t("memoryManageModal.shareOption.ask"),
      [MEMORY_SHARE_STRATEGY.NEVER]: t("memoryManageModal.shareOption.never"),
    };

    return (
      <Card className="mb-6 shadow-sm">
        <div className="flex items-center justify-between gap-8">
          <div className="flex items-center gap-4">
            <Settings className="size-5 text-gray-600" />
            <div className="flex flex-col">
              <span className="text-sm font-medium">
                {t("memoryManageModal.memoryAbility")}
              </span>
            </div>
          </div>
          <Switch
            checked={memory.memoryEnabled}
            onChange={memory.setMemoryEnabled}
          />
        </div>

        {memory.memoryEnabled && (
          <div className="flex items-center justify-between gap-8 mt-6 pt-6 border-t">
            <div className="flex items-center gap-4">
              <Share2 className="size-5 text-gray-600" />
              <div className="flex flex-col">
                <span className="text-sm font-medium">
                  {t("memoryManageModal.agentMemoryShare")}
                </span>
              </div>
            </div>
            <div className="flex gap-2">
              {Object.entries(shareOptionLabels).map(([key, label]) => (
                <Button
                  key={key}
                  type={memory.shareOption === key ? "primary" : "default"}
                  size="middle"
                  onClick={() =>
                    memory.setShareOption(key as MemoryShareStrategy)
                  }
                >
                  {label}
                </Button>
              ))}
            </div>
          </div>
        )}
      </Card>
    );
  };

  // Render add memory input (inline, doesn't expand container)
  const renderAddMemoryInput = (groupKey: string) => {
    if (memory.addingMemoryKey !== groupKey) return null;

    return (
      <div className="w-full flex items-center justify-center">
        <div className="w-full flex items-start gap-3">
          <Input.TextArea
            value={memory.newMemoryContent}
            onChange={(e) => memory.setNewMemoryContent(e.target.value)}
            placeholder={t("memoryManageModal.inputPlaceholder")}
            maxLength={500}
            showCount
            onPressEnter={memory.confirmAddingMemory}
            disabled={memory.isAddingMemory}
            className="flex-1"
            autoSize={{ minRows: 1, maxRows: 3 }}
            style={{ minHeight: "60px" }}
          />
          <div className="flex flex-col gap-2 flex-shrink-0 pt-1">
            <Button
              type="primary"
              size="middle"
              shape="circle"
              icon={<Check className="size-4" />}
              onClick={memory.confirmAddingMemory}
              loading={memory.isAddingMemory}
              disabled={!memory.newMemoryContent.trim()}
              className="bg-green-500 hover:bg-green-600"
            />
            <Button
              size="middle"
              shape="circle"
              icon={<X className="size-4" />}
              onClick={memory.cancelAddingMemory}
              disabled={memory.isAddingMemory}
            />
          </div>
        </div>
      </div>
    );
  };

  // Render single list (for tenant shared and user personal) - no card, with header buttons
  const renderSingleList = useCallback(
    (group: { title: string; key: string; items: any[] }) => {
      return (
        <div
          className="memory-single-list"
          key={`${group.key}-${group.items.length}-${memory.addingMemoryKey}`}
        >
          {/* Add memory input - appears before the list */}
          {memory.addingMemoryKey === group.key && (
            <div className="border border-gray-200 rounded-md p-3 mb-3 bg-blue-50">
              {renderAddMemoryInput(group.key)}
            </div>
          )}

          <List
            header={
              <div className="flex items-center justify-between">
                <span className="text-base font-medium">{group.title}</span>
                <div className="flex items-center gap-2">
                  <Button
                    type="text"
                    size="small"
                    icon={<MessageSquarePlus className="size-4" />}
                    onClick={() => {
                      memory.startAddingMemory(group.key);
                    }}
                    className="hover:bg-green-50 hover:text-green-600"
                    title={t("memoryManageModal.addMemory")}
                  />
                  {group.items.length > 0 && (
                    <Button
                      type="text"
                      size="small"
                      icon={<MessageSquareOff className="size-4" />}
                      onClick={() => handleClearConfirm(group.key, group.title)}
                      danger
                      className="hover:bg-red-50"
                      title={t("memoryManageModal.clearMemory")}
                    />
                  )}
                </div>
              </div>
            }
            bordered
            dataSource={group.items}
            locale={{
              emptyText: (
                <div className="flex flex-col items-center justify-center py-16 text-gray-400">
                  <MessageSquareDashed className="size-12 mb-3 opacity-50" />
                  <p className="text-sm">{t("memoryManageModal.noMemory")}</p>
                </div>
              ),
            }}
            style={{
              height:
                memory.addingMemoryKey === group.key
                  ? "calc(100vh - 380px)"
                  : "calc(100vh - 280px)",
              overflowY: "auto",
            }}
            renderItem={(item) => (
              <List.Item
                className="hover:bg-gray-50 transition-colors"
                actions={[
                  <Button
                    key="delete"
                    type="text"
                    size="small"
                    danger
                    icon={<Eraser className="size-4" />}
                    onClick={() =>
                      memory.handleDeleteMemory(item.id, group.key)
                    }
                    title={t("memoryManageModal.deleteMemory")}
                  />,
                ]}
              >
                <div className="flex flex-col text-sm">{item.memory}</div>
              </List.Item>
            )}
          />
        </div>
      );
    },
    [
      memory.addingMemoryKey,
      memory.startAddingMemory,
      memory.handleDeleteMemory,
      handleClearConfirm,
      renderAddMemoryInput,
      t,
    ]
  );

  const renderMemoryWithMenu = (
    groups: { title: string; key: string; items: any[] }[],
    showSwitch = false
  ) => (
    <MemoryMenuList
      groups={groups}
      showSwitch={showSwitch}
      memory={memory}
      t={t}
      onClearConfirm={handleClearConfirm}
      renderAddMemoryInput={renderAddMemoryInput}
    />
  );

  const tabItems = [
    {
      key: MEMORY_TAB_KEYS.BASE,
      label: (
        <span className="inline-flex items-center gap-2">
          <Settings className="size-4" />
          {t("memoryManageModal.baseSettings")}
        </span>
      ),
      children: renderBaseSettings(),
    },
 [
          {
            key: MEMORY_TAB_KEYS.TENANT,
            label: (
              <span className="inline-flex items-center gap-2">
                <UsersRound className="size-4" />
                {t("memoryManageModal.tenantShareTab")}
              </span>
            ),
            children: renderSingleList(memory.tenantSharedGroup),
            disabled: !memory.memoryEnabled,
          },
          {
            key: MEMORY_TAB_KEYS.AGENT_SHARED,
            label: (
              <span className="inline-flex items-center gap-2">
                <Share2 className="size-4" />
                {t("memoryManageModal.agentShareTab")}
              </span>
            ),
            children: renderMemoryWithMenu(memory.agentSharedGroups, true),
            disabled:
              !memory.memoryEnabled ||
              memory.shareOption === MEMORY_SHARE_STRATEGY.NEVER,
          },
        ],
    {
      key: MEMORY_TAB_KEYS.USER_PERSONAL,
      label: (
        <span className="inline-flex items-center gap-2">
          <UserRound className="size-4" />
          {t("memoryManageModal.userPersonalTab")}
        </span>
      ),
      children: renderSingleList(memory.userPersonalGroup),
      disabled: !memory.memoryEnabled,
    },
    {
      key: MEMORY_TAB_KEYS.USER_AGENT,
      label: (
        <span className="inline-flex items-center gap-2">
          <Bot className="size-4" />
          {t("memoryManageModal.userAgentTab")}
        </span>
      ),
      children: renderMemoryWithMenu(memory.userAgentGroups, true),
      disabled: !memory.memoryEnabled,
    },
  ];

  return (
    <>
      <div className="w-full h-full p-8">
        <motion.div
          initial="initial"
          animate="in"
          exit="out"
          variants={pageVariants}
          transition={pageTransition}
          style={{ width: "100%", height: "100%" }}
        >

            <div className="w-full h-full flex items-center justify-center">
              <div
                className="w-full mx-auto"
                style={{
                  maxWidth: SETUP_PAGE_CONTAINER.MAX_WIDTH,
                  padding: `0 ${SETUP_PAGE_CONTAINER.HORIZONTAL_PADDING}`,
                }}
              >
                <div
                  className={STANDARD_CARD.BASE_CLASSES}
                  style={{
                    height: SETUP_PAGE_CONTAINER.MAIN_CONTENT_HEIGHT,
                    padding: "25px",
                  }}
                >
                  <Tabs
                    size="middle"
                    items={tabItems as any}
                    activeKey={memory.activeTabKey}
                    onChange={(key) => memory.setActiveTabKey(key)}
                    tabBarStyle={{
                      marginBottom: "16px",
                    }}
                  />
                </div>
              </div>
            </div>
        </motion.div>
      </div>
    </>
  );
}

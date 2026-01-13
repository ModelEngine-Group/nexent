"use client";

import React, { useEffect, useState } from "react";
import { Button, List, Menu, Switch } from "antd";
import {
  MessageSquarePlus,
  Eraser,
  MessageSquareOff,
  MessageSquareDashed,
} from "lucide-react";
import { useTranslation } from "react-i18next";

interface MemoryMenuListProps {
  groups: { title: string; key: string; items: any[] }[];
  showSwitch?: boolean;
  memory: ReturnType<typeof import("@/hooks/useMemory").useMemory>;
  t: ReturnType<typeof useTranslation>["t"];
  onClearConfirm: (groupKey: string, groupTitle: string) => void;
  renderAddMemoryInput: (groupKey: string) => React.ReactNode;
}

export function MemoryMenuList({
  groups,
  showSwitch = false,
  memory,
  t,
  onClearConfirm,
  renderAddMemoryInput,
}: MemoryMenuListProps) {
  const [selectedKey, setSelectedKey] = useState<string>(
    groups.length > 0 ? groups[0].key : ""
  );

  useEffect(() => {
    if (!groups.some((group) => group.key === selectedKey)) {
      setSelectedKey(groups[0]?.key ?? "");
    }
  }, [groups, selectedKey]);

  if (groups.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <MessageSquareDashed className="size-16 mb-4 text-gray-300" />
        <p className="text-base text-gray-500">
          {t("memoryManageModal.noMemory")}
        </p>
      </div>
    );
  }

  const currentGroup = groups.find((g) => g.key === selectedKey) || groups[0];
  const isPlaceholder = /-placeholder$/.test(currentGroup.key);
  const disabled = !isPlaceholder && !!memory.disabledGroups[currentGroup.key];

  const menuItems = groups.map((g) => {
    const groupDisabled =
      !/-placeholder$/.test(g.key) && !!memory.disabledGroups[g.key];
    return {
      key: g.key,
      label: (
        <div className="flex items-center justify-between w-full">
          <span className="truncate">{g.title}</span>
          {showSwitch && !/-placeholder$/.test(g.key) && (
            <div onClick={(e) => e.stopPropagation()}>
              <Switch
                size="small"
                checked={!groupDisabled}
                onChange={(val) => memory.toggleGroup(g.key, val)}
              />
            </div>
          )}
        </div>
      ),
      disabled: groupDisabled,
    };
  });

  return (
    <div className="w-full h-full p-8">
      <Menu
        mode="inline"
        selectedKeys={[selectedKey]}
        onClick={({ key }) => setSelectedKey(key)}
        items={menuItems}
        style={{ width: 280, height: "100%", overflowY: "auto" }}
      />

      <div className="flex-1">
        {/* Add memory input - appears before the list */}
        {memory.addingMemoryKey === currentGroup.key && (
          <div className="border border-gray-200 rounded-md p-3 mb-3 bg-blue-50">
            {renderAddMemoryInput(currentGroup.key)}
          </div>
        )}

        <List
          header={
            <div className="flex items-center justify-between">
              <span className="text-base font-medium">
                {currentGroup.title}
              </span>
              <div className="flex items-center gap-2">
                <Button
                  type="text"
                  size="small"
                  icon={<MessageSquarePlus className="size-4" />}
                  onClick={() => {
                    memory.startAddingMemory(currentGroup.key);
                  }}
                  disabled={disabled}
                  className="hover:bg-green-50 hover:text-green-600"
                  title={t("memoryManageModal.addMemory")}
                />
                {currentGroup.items.length > 0 && (
                  <Button
                    type="text"
                    size="small"
                    icon={<MessageSquareOff className="size-4" />}
                    onClick={() =>
                      !isPlaceholder &&
                      onClearConfirm(currentGroup.key, currentGroup.title)
                    }
                    disabled={disabled}
                    danger
                    className="hover:bg-red-50"
                    title={t("memoryManageModal.clearMemory")}
                  />
                )}
              </div>
            </div>
          }
          bordered
          dataSource={currentGroup.items}
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
              memory.addingMemoryKey === currentGroup.key
                ? "calc(100% - 100px)"
                : "100%",
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
                    memory.handleDeleteMemory(item.id, currentGroup.key)
                  }
                  disabled={disabled}
                  title={t("memoryManageModal.deleteMemory")}
                />,
              ]}
            >
              <div className="flex flex-col text-sm">{item.memory}</div>
            </List.Item>
          )}
        />
      </div>
    </div>
  );
}






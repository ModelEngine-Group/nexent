"use client";

import { useState, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Dropdown, Badge, Modal, Button } from "antd";
import { DownOutlined } from "@ant-design/icons";
import { WarningFilled } from "@ant-design/icons";
import { BrainCircuit, Globe } from "lucide-react";

import { Button as ButtonUI } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { languageOptions } from "@/const/constants";
import { useLanguageSwitch } from "@/lib/language";
import { useMemoryIndicator } from "@/hooks/useMemory";
import { loadMemoryConfig, setMemorySwitch } from "@/services/memoryService";
import { configStore } from "@/lib/config";
import log from "@/lib/logger";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { USER_ROLES } from "@/const/modelConfig";

import MemoryManageModal from "../internal/memory/memoryManageModal";

// Gradient definition for BrainCircuit icon
const GradientDefs = () => (
  <svg width="0" height="0" className="absolute">
    <defs>
      <linearGradient id="brainCogGradient" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stopColor="#3b82f6" />
        <stop offset="100%" stopColor="#9333ea" />
      </linearGradient>
    </defs>
  </svg>
);

interface ChatHeaderProps {
  title: string;
  onRename?: (newTitle: string) => void;
}

export function ChatHeader({ title, onRename }: ChatHeaderProps) {
  const router = useRouter();
  const [isEditing, setIsEditing] = useState(false);
  const [editTitle, setEditTitle] = useState(title);
  const [memoryModalVisible, setMemoryModalVisible] = useState(false);
  const [embeddingConfigured, setEmbeddingConfigured] = useState<boolean>(true);
  const [showConfigPrompt, setShowConfigPrompt] = useState(false);
  const [showAutoOffPrompt, setShowAutoOffPrompt] = useState(false);
  const hasNewMemory = useMemoryIndicator(memoryModalVisible);
  const inputRef = useRef<HTMLInputElement>(null);
  const { t } = useTranslation("common");
  const { currentLanguage, handleLanguageChange } = useLanguageSwitch();
  const { user } = useAuth();
  const isAdmin = user?.role === USER_ROLES.ADMIN;

  const goToModelSetup = () => {
    router.push(`/${currentLanguage}/setup/models`);
  };

  // Update editTitle when the title attribute changes
  useEffect(() => {
    setEditTitle(title);
  }, [title]);

  // Handle double-click event
  const handleDoubleClick = () => {
    setIsEditing(true);
    // Delay focusing to ensure the DOM has updated
    setTimeout(() => {
      if (inputRef.current) {
        inputRef.current.focus();
        inputRef.current.select();
      }
    }, 10);
  };

  // Check embedding configuration and memory switch once when entering the page
  useEffect(() => {
    try {
      const modelConfig = configStore.getModelConfig();
      const configured = Boolean(
        modelConfig?.embedding?.modelName ||
          modelConfig?.multiEmbedding?.modelName
      );
      setEmbeddingConfigured(configured);

      if (!configured) {
        // If memory switch is on, turn it off automatically and notify the user
        loadMemoryConfig()
          .then(async (cfg) => {
            if (cfg.memoryEnabled) {
              const ok = await setMemorySwitch(false);
              if (!ok) {
                log.warn(
                  "Failed to auto turn off memory switch when embedding is not configured"
                );
              }
              setShowAutoOffPrompt(true);
            }
          })
          .catch((e) => {
            log.error("Failed to check memory config on page enter", e);
          });
      }
    } catch (e) {
      setEmbeddingConfigured(false);
      log.error("Failed to read model config for embedding check", e);
    }
  }, []);

  // Handle submit editing
  const handleSubmit = () => {
    const trimmedTitle = editTitle.trim();
    if (trimmedTitle && onRename && trimmedTitle !== title) {
      onRename(trimmedTitle);
    } else {
      setEditTitle(title); // If empty or unchanged, restore the original title
    }
    setIsEditing(false);
  };

  // Handle keydown event
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      handleSubmit();
    } else if (e.key === "Escape") {
      setEditTitle(title);
      setIsEditing(false);
    }
  };

  return (
    <>
      <GradientDefs />
      <header className="border-b border-transparent bg-background z-10">
        <div className="p-3 pb-1">
          <div className="relative flex flex-1">
            <div className="absolute left-0 top-1/2 transform -translate-y-1/2">
              {/* Left button area */}
            </div>

            <div className="w-full flex justify-center">
              <div className="max-w-3xl w-full flex justify-center mt-2 mb-0">
                {isEditing ? (
                  <Input
                    ref={inputRef}
                    value={editTitle}
                    onChange={(e) => setEditTitle(e.target.value)}
                    onKeyDown={handleKeyDown}
                    onBlur={handleSubmit}
                    className="text-xl font-bold text-center h-9 max-w-xs"
                    autoFocus
                  />
                ) : (
                  <h1
                    className="text-xl font-bold cursor-pointer px-2 py-1 rounded border border-transparent hover:border-slate-200"
                    onDoubleClick={handleDoubleClick}
                    title={t("chatHeader.doubleClickToEdit")}
                  >
                    {title}
                  </h1>
                )}
              </div>
            </div>

            <div className="absolute right-0 top-1/2 transform -translate-y-1/2 flex items-center space-x-1 gap-1">
              {/* Language Switch */}
              <Dropdown
                menu={{
                  items: languageOptions.map((opt) => ({
                    key: opt.value,
                    label: opt.label,
                  })),
                  onClick: ({ key }) => handleLanguageChange(key as string),
                }}
              >
                <a className="ant-dropdown-link text-sm font-medium text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white transition-colors flex items-center gap-2 cursor-pointer w-[100px] border-0 shadow-none bg-transparent text-left">
                  <Globe className="h-4 w-4" />
                  {languageOptions.find((o) => o.value === currentLanguage)
                    ?.label || currentLanguage}
                  <DownOutlined className="text-[10px]" />
                </a>
              </Dropdown>
              {/* Memory Setting */}
              <Badge dot={embeddingConfigured && hasNewMemory} offset={[-4, 4]}>
                <ButtonUI
                  variant="ghost"
                  className={`mr-4 rounded-full px-2 py-1 h-7 flex items-center gap-2 hover:bg-slate-100 dark:hover:bg-slate-800 ${
                    !embeddingConfigured ? "opacity-50" : ""
                  }`}
                  onClick={() => {
                    if (!embeddingConfigured) {
                      setShowConfigPrompt(true);
                      return;
                    }
                    setMemoryModalVisible(true);
                  }}
                >
                  <BrainCircuit
                    className="size-5"
                    stroke="url(#brainCogGradient)"
                  />
                  <span className="text-sm font-medium text-slate-600 dark:text-slate-300">
                    {t("memoryManageModal.title")}
                  </span>
                </ButtonUI>
              </Badge>
            </div>
          </div>
        </div>
      </header>
      {/* Embedding not configured prompt */}
      <Modal
        title={t("embedding.chatMemoryWarningModal.title")}
        open={showConfigPrompt}
        onCancel={() => setShowConfigPrompt(false)}
        centered
        footer={
          <div className="flex justify-end mt-3 gap-4">
            {isAdmin && (
              <Button type="primary" onClick={goToModelSetup}>
                {t("embedding.chatMemoryWarningModal.ok_config")}
              </Button>
            )}
            <Button onClick={() => setShowConfigPrompt(false)}>
              {t("embedding.chatMemoryWarningModal.ok")}
            </Button>
          </div>
        }
      >
        <div className="py-2">
          <div className="flex items-center">
            <WarningFilled
              className="text-yellow-500 mt-1 mr-2"
              style={{ fontSize: "48px" }}
            />
            <div className="ml-3 mt-2">
              <div className="text-sm leading-6">
                {t("embedding.chatMemoryWarningModal.content")}
              </div>
              {!isAdmin && (
                <div className="mt-2 text-xs opacity-70">
                  {t("embedding.chatMemoryWarningModal.tip")}
                </div>
              )}
            </div>
          </div>
        </div>
      </Modal>

      {/* Auto-off memory prompt when embedding missing */}
      <Modal
        title={t("embedding.chatMemoryAutoDeselectModal.title")}
        open={showAutoOffPrompt}
        onCancel={() => setShowAutoOffPrompt(false)}
        centered
        footer={
          <div className="flex justify-end mt-3 gap-4">
            {isAdmin && (
              <Button type="primary" onClick={goToModelSetup}>
                {t("embedding.chatMemoryAutoDeselectModal.ok_config")}
              </Button>
            )}
            <Button onClick={() => setShowAutoOffPrompt(false)}>
              {t("embedding.chatMemoryAutoDeselectModal.ok")}
            </Button>
          </div>
        }
      >
        <div className="py-2">
          <div className="flex items-center">
            <WarningFilled
              className="text-yellow-500 mt-1 mr-2"
              style={{ fontSize: "48px" }}
            />
            <div className="ml-3 mt-2">
              <div className="text-sm leading-6">
                {t("embedding.chatMemoryAutoDeselectModal.content")}
              </div>
              {!isAdmin && (
                <div className="mt-2 text-xs opacity-70">
                  {t("embedding.chatMemoryAutoDeselectModal.tip")}
                </div>
              )}
            </div>
          </div>
        </div>
      </Modal>
      <MemoryManageModal
        visible={memoryModalVisible}
        onClose={() => setMemoryModalVisible(false)}
      />
    </>
  );
}

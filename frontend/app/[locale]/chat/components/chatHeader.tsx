"use client";

import { useState, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";

import { Input } from "@/components/ui/input";
import { Button, Tooltip } from "antd";
import { CalendarClock, Share2, X } from "lucide-react";
import { loadMemoryConfig, setMemorySwitch } from "@/services/memoryService";
import { useConfig } from "@/hooks/useConfig";
import log from "@/lib/logger";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { USER_ROLES } from "@/const/auth";
import { useConfirmModal } from "@/hooks/useConfirmModal";

interface ChatHeaderProps {
  title: string;
  onRename?: (newTitle: string) => void;
  onShareClick?: () => void;
  isShareMode?: boolean;
  hasAutomation?: boolean;
}

export function ChatHeader({
  title,
  onRename,
  onShareClick,
  isShareMode = false,
  hasAutomation = false,
}: ChatHeaderProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editTitle, setEditTitle] = useState(title);

  const inputRef = useRef<HTMLInputElement>(null);
  const { t, i18n } = useTranslation("common");
  const { user } = useAuthorizationContext();
  const { isSpeedMode } = useDeployment();
  const { confirm } = useConfirmModal();
  const { modelConfig } = useConfig();
  const isAdmin = isSpeedMode || user?.role === USER_ROLES.ADMIN;

  const showAutoOffConfirm = () => {
    confirm({
      title: t("embedding.chatMemoryAutoDeselectModal.title"),
      content: (
        <div className="py-2">
          <div className="text-sm leading-6">
            {t("embedding.chatMemoryAutoDeselectModal.content")}
          </div>
          {!isAdmin && (
            <div className="mt-2 text-xs opacity-70">
              {t("embedding.chatMemoryAutoDeselectModal.tip")}
            </div>
          )}
        </div>
      ),
    });
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
      const configured = Boolean(
        modelConfig?.embedding?.modelName ||
        modelConfig?.multiEmbedding?.modelName
      );

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
              showAutoOffConfirm();
            }
          })
          .catch((e) => {
            log.error("Failed to check memory config on page enter", e);
          });
      }
    } catch (e) {
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
      <header className="border-b border-transparent bg-background">
        <div className="w-full grid grid-cols-[1fr_auto_1fr] items-center pt-4 pb-2 px-4">
          <div />
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
            <div className="flex items-center justify-center gap-2 min-w-0">
              <h1
                className="text-xl font-bold cursor-pointer px-2 py-1 rounded border border-transparent hover:border-slate-200 truncate"
                onDoubleClick={handleDoubleClick}
                title={t("chatHeader.doubleClickToEdit")}
              >
                {title}
              </h1>
              {hasAutomation && (
                <Tooltip
                  title={t("agentAutomation.boundTask", "已绑定自动任务")}
                >
                  <CalendarClock className="h-4 w-4 shrink-0 text-blue-600" />
                </Tooltip>
              )}
            </div>
          )}
          <div className="flex justify-end">
            {onShareClick && (
              <Tooltip
                title={
                  isShareMode
                    ? t("common.cancel", "Cancel")
                    : t("chatHeader.share", "Share")
                }
              >
                <Button
                  type={isShareMode ? "default" : "text"}
                  shape="circle"
                  icon={isShareMode ? <X size={16} /> : <Share2 size={16} />}
                  onClick={onShareClick}
                />
              </Tooltip>
            )}
          </div>
        </div>
      </header>
    </>
  );
}

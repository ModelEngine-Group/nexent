"use client";

import { useState, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "antd";

import { Input } from "@/components/ui/input";
import { loadMemoryConfig, setMemorySwitch } from "@/services/memoryService";
import { configStore } from "@/lib/config";
import log from "@/lib/logger";
import { useRouter } from "next/navigation";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import { USER_ROLES } from "@/const/auth";
import { saveView } from "@/lib/viewPersistence";
import { useConfirmModal } from "@/hooks/useConfirmModal";

interface ChatHeaderProps {
  title: string;
  onRename?: (newTitle: string) => void;
}

export function ChatHeader({ title, onRename }: ChatHeaderProps) {
  const router = useRouter();
  const [isEditing, setIsEditing] = useState(false);
  const [editTitle, setEditTitle] = useState(title);


  const inputRef = useRef<HTMLInputElement>(null);
  const { t, i18n } = useTranslation("common");
  const { user } = useAuthorizationContext();
  const { isSpeedMode } = useDeployment();
  const { confirm } = useConfirmModal();
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
      const modelConfig = configStore.getModelConfig();
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
              {/* Right side controls - now handled by navigation bar */}
            </div>
          </div>
        </div>
      </header>

    </>
  );
}

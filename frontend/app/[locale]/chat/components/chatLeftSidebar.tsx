import { useState, useRef, useEffect } from "react";
import {
  Clock,
  Plus,
  Pencil,
  Trash2,
  MoreHorizontal,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { useRouter } from "next/navigation";

import { Button, Dropdown } from "antd";
import { Input } from "@/components/ui/input";
import { Tooltip, TooltipProvider } from "@/components/ui/tooltip";
import { StaticScrollArea } from "@/components/ui/scrollArea";
import { useTranslation } from "react-i18next";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import { ConversationListItem, ChatSidebarProps } from "@/types/chat";

// conversation status indicator component
const ConversationStatusIndicator = ({
  isStreaming,
  isCompleted,
}: {
  isStreaming: boolean;
  isCompleted: boolean;
}) => {
  const { t } = useTranslation();

  if (isStreaming) {
    return (
      <div
        className="flex-shrink-0 w-2 h-2 bg-green-500 rounded-full mr-2 animate-pulse"
        title={t("chatLeftSidebar.running")}
      />
    );
  }

  if (isCompleted) {
    return (
      <div
        className="flex-shrink-0 w-2 h-2 bg-blue-500 rounded-full mr-2"
        title={t("chatLeftSidebar.completed")}
      />
    );
  }

  return null;
};

// Helper function - dialog classification
const categorizeDialogs = (dialogs: ConversationListItem[]) => {
  const now = new Date();
  const today = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate()
  ).getTime();
  const weekAgo = today - 7 * 24 * 60 * 60 * 1000;

  const todayDialogs: ConversationListItem[] = [];
  const weekDialogs: ConversationListItem[] = [];
  const olderDialogs: ConversationListItem[] = [];

  dialogs.forEach((dialog) => {
    const dialogTime = dialog.create_time;

    if (dialogTime >= today) {
      todayDialogs.push(dialog);
    } else if (dialogTime >= weekAgo) {
      weekDialogs.push(dialog);
    } else {
      olderDialogs.push(dialog);
    }
  });

  return {
    today: todayDialogs,
    week: weekDialogs,
    older: olderDialogs,
  };
};

export function ChatSidebar({
  conversationList,
  selectedConversationId,
  openDropdownId,
  streamingConversations,
  completedConversations,
  onNewConversation,
  onDialogClick,
  onRename,
  onDelete,
  onSettingsClick,
  onDropdownOpenChange,
  onToggleSidebar,
  expanded,
  userEmail,
  userAvatarUrl
}: ChatSidebarProps) {
  const { t } = useTranslation();
  const { confirm } = useConfirmModal();
  const router = useRouter();
  const { today, week, older } = categorizeDialogs(conversationList);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const [animationComplete, setAnimationComplete] = useState(false);

  useEffect(() => {
    // Reset animation state when expanded changes
    setAnimationComplete(false);

    // Set animation complete after the transition duration (200ms)
    const timer = setTimeout(() => {
      setAnimationComplete(true);
    }, 200);

    return () => clearTimeout(timer);
  }, [expanded]);

  // Handle edit start
  const handleStartEdit = (dialogId: number, title: string) => {
    setEditingId(dialogId);
    setEditingTitle(title);
    // Close any open dropdown menus
    onDropdownOpenChange(false, null);

    // Use setTimeout to ensure that the input box is focused after the DOM is updated
    setTimeout(() => {
      if (inputRef.current) {
        inputRef.current.focus();
        inputRef.current.select();
      }
    }, 10);
  };

  // Handle edit submission
  const handleSubmitEdit = () => {
    if (editingId !== null && editingTitle.trim()) {
      onRename(editingId, editingTitle.trim());
      setEditingId(null);
    }
  };

  // Handle edit cancellation
  const handleCancelEdit = () => {
    setEditingId(null);
  };

  // Handle key events
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      handleSubmitEdit();
    } else if (e.key === "Escape") {
      handleCancelEdit();
    }
  };

  // Handle delete click
  const handleDeleteClick = (dialogId: number) => {
    // Close dropdown menus
    onDropdownOpenChange(false, null);

    // Show confirmation modal
    confirm({
      title: t("chatLeftSidebar.confirmDeletionTitle"),
      content: t("chatLeftSidebar.confirmDeletionDescription"),
      onOk: () => {
        onDelete(dialogId);
      },
    });
  };

  // Render dialog list items
  const renderDialogList = (dialogs: ConversationListItem[], title: string) => {
    if (dialogs.length === 0) return null;

    return (
      <div className="space-y-1">
        <p
          className="px-2 pr-3 text-sm font-medium text-gray-500 tracking-wide font-sans py-1"
          style={{
            fontWeight: "bold",
            color: "#4d4d4d",
            backgroundColor: "rgb(242 248 255)",
            fontSize: "16px",
            whiteSpace: "nowrap",
          }}
        >
          {title}
        </p>
        {dialogs.map((dialog) => (
          <div
            key={dialog.conversation_id}
            className={`flex items-center group rounded-md ${
              selectedConversationId === dialog.conversation_id
                ? "bg-blue-100"
                : "hover:bg-slate-100"
            }`}
          >
            {editingId === dialog.conversation_id ? (
              // Edit mode
              <div className="flex-1 px-3 py-2">
                <Input
                  ref={inputRef}
                  value={editingTitle}
                  onChange={(e) => setEditingTitle(e.target.value)}
                  onKeyDown={handleKeyDown}
                  onBlur={handleSubmitEdit}
                  className="h-8 text-base"
                  autoFocus
                />
              </div>
            ) : (
              // Display mode
              <>
                <TooltipProvider>
                  <Tooltip
                    title={
                      <p className="break-words">{dialog.conversation_title}</p>
                    }
                    placement="right"
                    styles={{ root: { maxWidth: "300px" } }}
                  >
                    <Button
                      type="text"
                      size="middle"
                      className="flex-1 justify-start text-left min-w-0 max-w-[250px] px-3 py-2 h-auto border-0 shadow-none bg-transparent hover:!bg-transparent active:!bg-transparent"
                      onClick={() => onDialogClick(dialog)}
                    >
                      <ConversationStatusIndicator
                        isStreaming={streamingConversations.has(
                          dialog.conversation_id
                        )}
                        isCompleted={completedConversations.has(
                          dialog.conversation_id
                        )}
                      />
                      <span className="truncate block text-base font-normal text-gray-800 tracking-wide font-sans">
                        {dialog.conversation_title}
                      </span>
                    </Button>
                  </Tooltip>
                </TooltipProvider>

                <Dropdown
                  open={openDropdownId === dialog.conversation_id.toString()}
                  onOpenChange={(open) =>
                    onDropdownOpenChange(
                      open,
                      dialog.conversation_id.toString()
                    )
                  }
                  menu={{
                    items: [
                      {
                        key: "rename",
                        label: (
                          <span className="flex items-center">
                            <Pencil className="mr-2 h-5 w-5" />
                            {t("chatLeftSidebar.rename")}
                          </span>
                        ),
                      },
                      {
                        key: "delete",
                        label: (
                          <span className="flex items-center text-red-500">
                            <Trash2 className="mr-2 h-5 w-5" />
                            {t("chatLeftSidebar.delete")}
                          </span>
                        ),
                      },
                    ],
                    onClick: ({ key }) => {
                      if (key === "rename") {
                        handleStartEdit(
                          dialog.conversation_id,
                          dialog.conversation_title
                        );
                      } else if (key === "delete") {
                        handleDeleteClick(dialog.conversation_id);
                      }
                    },
                  }}
                  placement="bottomRight"
                  trigger={["click"]}
                >
                  <Button
                    type="text"
                    size="small"
                    className="h-6 w-6 min-w-[24px] p-0 flex-shrink-0 opacity-0 group-hover:opacity-100 hover:bg-slate-100 hover:border hover:border-slate-200 mr-1 focus:outline-none focus:ring-0 rounded-full transition-opacity duration-200 flex items-center justify-center"
                  >
                    <MoreHorizontal className="h-4 w-4" />
                  </Button>
                </Dropdown>
              </>
            )}
          </div>
        ))}
      </div>
    );
  };

  // Render collapsed state sidebar
  const renderCollapsedSidebar = () => {
    return (
      <>
        {/* Expand/Collapse button */}
        <div className="py-3 flex justify-center">
          <TooltipProvider>
            <Tooltip
              title={t("chatLeftSidebar.expandSidebar")}
              placement="right"
            >
              <Button
                type="text"
                size="middle"
                className="h-10 w-10 min-w-[40px] p-0 flex-shrink-0 hover:bg-slate-100 active:bg-slate-200 flex items-center justify-center rounded-full transition-colors duration-200"
                onClick={onToggleSidebar}
              >
                <ChevronRight className="h-5 w-5" />
              </Button>
            </Tooltip>
          </TooltipProvider>
        </div>

        {/* New conversation button */}
        <div className="py-3 flex justify-center">
          <TooltipProvider>
            <Tooltip
              title={t("chatLeftSidebar.newConversation")}
              placement="right"
            >
              <Button
                type="text"
                size="middle"
                className="h-10 w-10 min-w-[40px] p-0 flex-shrink-0 hover:bg-slate-100 active:bg-slate-200 flex items-center justify-center rounded-full transition-colors duration-200"
                onClick={onNewConversation}
              >
                <Plus className="h-5 w-5" />
              </Button>
            </Tooltip>
          </TooltipProvider>
        </div>

        {/* Spacer */}
        <div className="flex-1" />
      </>
    );
  };

  return (
    <>
      <div
        className="hidden md:flex w-64 flex-col border-r border-transparent bg-primary/5 text-base transition-all duration-300 ease-in-out overflow-hidden"
        style={{ width: expanded ? "300px" : "70px" }}
      >
        {expanded || !animationComplete ? (
          <div className="hidden md:flex flex-col h-full overflow-hidden">
            <div className="m-4 mt-3">
              <div className="flex items-center gap-2">
                <Button
                  type="default"
                  size="middle"
                  className="flex-1 justify-start text-base overflow-hidden h-10 border border-slate-300 hover:border-slate-400 hover:bg-white transition-colors duration-200"
                  onClick={onNewConversation}
                >
                  <Plus
                    className="mr-2 flex-shrink-0"
                    style={{ height: "20px", width: "20px" }}
                  />
                  <span className="truncate">
                    {t("chatLeftSidebar.newConversation")}
                  </span>
                </Button>
                <TooltipProvider>
                  <Tooltip>
                    <Tooltip title={t("chatLeftSidebar.collapseSidebar")}>
                      <Button
                        type="text"
                        size="middle"
                        className="h-10 w-10 min-w-[40px] p-0 flex-shrink-0 hover:bg-slate-100 active:bg-slate-200 flex items-center justify-center rounded-full transition-colors duration-200"
                        onClick={onToggleSidebar}
                      >
                        <ChevronLeft className="h-5 w-5" />
                      </Button>
                    </Tooltip>
                  </Tooltip>
                </TooltipProvider>
              </div>
            </div>

            <StaticScrollArea className="flex-1 m-2">
              <div className="space-y-4 pr-2">
                {conversationList.length > 0 ? (
                  <>
                    {renderDialogList(today, t("chatLeftSidebar.today"))}
                    {renderDialogList(week, t("chatLeftSidebar.last7Days"))}
                    {renderDialogList(older, t("chatLeftSidebar.older"))}
                  </>
                ) : (
                  <div className="space-y-1">
                    <p className="px-2 text-sm font-medium text-muted-foreground">
                      {t("chatLeftSidebar.recentConversations")}
                    </p>
                    <Button
                      type="text"
                      size="middle"
                      className="w-full justify-start flex items-center px-3 py-2 h-auto hover:bg-slate-50 transition-colors duration-200"
                    >
                      <Clock className="mr-2 h-5 w-5" />
                      {t("chatLeftSidebar.noHistory")}
                    </Button>
                  </div>
                )}
              </div>
            </StaticScrollArea>
          </div>
        ) : (
          renderCollapsedSidebar()
        )}
      </div>
    </>
  );
}

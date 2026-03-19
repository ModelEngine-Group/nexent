import { useState } from "react";
import {
  Clock,
  Plus,
  Pencil,
  Trash2,
  MoreHorizontal,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";

import { Button, Dropdown, Input, Layout, Tooltip, message } from "antd";
import { useTranslation } from "react-i18next";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import { conversationService } from "@/services/conversationService";
import {
  type ConversationManagement,
} from "@/hooks/chat/useConversationManagement";
import { ConversationListItem, SettingsMenuItem } from "@/types/chat";
import log from "@/lib/logger";

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
const categorizeConversations = (conversations: ConversationListItem[]) => {
  const now = new Date();
  const today = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate()
  ).getTime();
  const weekAgo = today - 7 * 24 * 60 * 60 * 1000;

  const todayConversations: ConversationListItem[] = [];
  const weekConversations: ConversationListItem[] = [];
  const olderConversations: ConversationListItem[] = [];

  conversations.forEach((conversations) => {
    const conversationTime = conversations.create_time;

    if (conversationTime >= today) {
      todayConversations.push(conversations);
    } else if (conversationTime >= weekAgo) {
      weekConversations.push(conversations);
    } else {
      olderConversations.push(conversations);
    }
  });

  return {
    today: todayConversations,
    week: weekConversations,
    older: olderConversations,
  };
};

// Chat sidebar props type
export interface ChatSidebarProps {
  streamingConversations: Set<number>;
  completedConversations: Set<number>;
  conversationManagement: ConversationManagement;
  /** Called when user clicks a conversation - loads messages and updates selection */
  onConversationSelect: (conversation: ConversationListItem) => void | Promise<void>;
}

const CONVERSATION_TITLE_MAX_LENGTH = 100;

export function ChatSidebar({
  streamingConversations,
  completedConversations,
  conversationManagement,
  onConversationSelect,
}: ChatSidebarProps) {
  const { t } = useTranslation();
  const { confirm } = useConfirmModal();
  const { today, week, older } = categorizeConversations(conversationManagement.conversationList);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [renameError, setRenameError] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [openDropdownId, setOpenDropdownId] = useState<number | null>(null);

  const onToggleSidebar = () => setCollapsed((prev) => !prev);

  const handleRenameClick = (conversationId: number, currentTitle: string) => {
    setEditingId(conversationId);
    setRenameValue(currentTitle);
    setRenameError(null);
    setOpenDropdownId(null);
  };

  const validateRenameTitle = (title: string): string | null => {
    const trimmedTitle = title.trim();
    if (!trimmedTitle) {
      return t("chatLeftSidebar.renameErrorEmpty");
    }
    if (trimmedTitle.length > CONVERSATION_TITLE_MAX_LENGTH) {
      return t("chatLeftSidebar.renameErrorTooLong", {
        max: CONVERSATION_TITLE_MAX_LENGTH,
      });
    }
    return null;
  };

  const handleRename = async (conversationId: number, newTitle: string) => {
    const trimmedTitle = newTitle.trim();
    if (!trimmedTitle) return false;
    try {
      await conversationService.rename(conversationId, trimmedTitle);
      await conversationManagement.fetchConversationList();
      if (conversationManagement.selectedConversationId === conversationId) {
        conversationManagement.setConversationTitle(trimmedTitle);
      }
      setEditingId(null);
      setRenameError(null);
      return true;
    } catch (error) {
      log.error(t("chatInterface.renameFailed"), error);
      setRenameError(t("chatLeftSidebar.renameErrorSubmitFailed"));
      message.error(t("chatLeftSidebar.renameErrorSubmitFailed"));
      return false;
    }
  };

  const handleRenameSubmit = async (conversationId: number) => {
    const validationError = validateRenameTitle(renameValue);
    if (validationError) {
      setRenameError(validationError);
      message.warning(validationError);
      return;
    }

    const success = await handleRename(conversationId, renameValue);
    if (success) {
      setRenameValue("");
    }
  };

  const handleRenameCancel = () => {
    setEditingId(null);
    setRenameValue("");
    setRenameError(null);
  };

  // Handle delete
  const handleDelete = (conversationId: number) => {

    confirm({
      title: t("chatLeftSidebar.confirmDeletionTitle"),
      content: t("chatLeftSidebar.confirmDeletionDescription"),
      onOk: async () => {
        try {
          await conversationService.delete(conversationId);
          await conversationManagement.fetchConversationList();
          if (conversationManagement.selectedConversationId === conversationId) {
            conversationManagement.setSelectedConversationId(null);
            conversationManagement.setConversationTitle(
              t("chatInterface.newConversation")
            );
            conversationManagement.handleNewConversation();
          }
        } catch (error) {
          log.error(t("chatInterface.deleteFailed"), error);
        }
      },
    });
  };

  // Render dialog list items
  const renderConversationList = (conversation: ConversationListItem[], title: string) => {
    if (conversation.length === 0) return null;

    return (
      <div className="space-y-1 h-full w-full">
        <p
          className="flex items-center gap-1.5 px-3 py-1.5 text-s font-medium tracking-wide text-neutral-500 rounded-r whitespace-nowrap"
        >
          {title}
        </p>
        {conversation.map((conversation) => {
          const isEditing = editingId === conversation.conversation_id;
          return (
            <div
              key={conversation.conversation_id}
              className={`flex items-center group rounded-md ${
                conversationManagement.selectedConversationId ===
                conversation.conversation_id
                  ? "bg-blue-100"
                  : "hover:bg-slate-100"
              }`}
            >
            <div className="flex-1 min-w-0 overflow-hidden">
              <Tooltip
                title={!isEditing ? (
                  <span className="break-words max-w-[300px] block">
                    {conversation.conversation_title}
                  </span>
                ) : null}
                placement="bottom"
              >
                <div
                  className="flex items-center min-h-10 min-w-0 w-full px-3 py-1 cursor-pointer"
                  onClick={() => {
                    if (!isEditing) {
                      onConversationSelect(conversation);
                    }
                  }}
                >
                  <ConversationStatusIndicator
                    isStreaming={streamingConversations.has(
                      conversation.conversation_id
                    )}
                    isCompleted={completedConversations.has(
                      conversation.conversation_id
                    )}
                  />
                  <div className="chat-sidebar-editable-title flex items-center self-stretch flex-1 min-w-0 overflow-hidden">
                    {isEditing ? (
                      <Input
                        autoFocus
                        size="small"
                        value={renameValue}
                        status={renameError ? "error" : ""}
                        onChange={(event) => {
                          const nextValue = event.target.value;
                          setRenameValue(nextValue);
                          setRenameError(validateRenameTitle(nextValue));
                        }}
                        onPressEnter={() => handleRenameSubmit(conversation.conversation_id)}
                        onBlur={() => handleRenameSubmit(conversation.conversation_id)}
                        onKeyDown={(event) => {
                          if (event.key === "Escape") {
                            event.preventDefault();
                            handleRenameCancel();
                          }
                        }}
                        onClick={(event) => event.stopPropagation()}
                        className="ml-0.5 flex-1 min-w-0 !h-8 !leading-8 !py-0 !text-base whitespace-nowrap"
                      />
                    ) : (
                      <span className="chat-sidebar-title-fade block whitespace-nowrap text-base font-normal text-gray-800 tracking-wide font-sans ml-0.5 flex-1 min-w-0 overflow-hidden [text-overflow:clip]">
                        {conversation.conversation_title}
                      </span>
                    )}
                </div>
              </div>
            </Tooltip>
            </div>

            <div
              className={`shrink-0 overflow-hidden flex items-center justify-center transition-opacity duration-150 ${
                openDropdownId === conversation.conversation_id
                  ? "w-9 opacity-100"
                  : "w-0 opacity-0 group-hover:w-9 group-hover:opacity-100"
              }`}
            >
              <Dropdown
              onOpenChange={(open) => setOpenDropdownId(open ? conversation.conversation_id : null)}
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
                    handleRenameClick(
                      conversation.conversation_id,
                      conversation.conversation_title
                    );
                  } else if (key === "delete") {
                    handleDelete(conversation.conversation_id);
                  }
                },
              }}
              placement="bottomRight"
              trigger={["click"]}
            >
              <Button
                type="text"
                size="small"
                className="hover:!bg-transparent text-neutral-500"
              >
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </Dropdown>
            </div>
            </div>
          );
        })}
      </div>
    );
  };

  // Render collapsed state sidebar
  const renderCollapsedSidebar = () => {
    return (
      <>
        {/* Expand/Collapse button */}
        <div className="py-3 flex justify-center">
          <Tooltip title={t("chatLeftSidebar.expandSidebar")} placement="right">
            <Button
              type="text"
              size="middle"
              className="h-10 w-10 min-w-[40px] p-0 flex-shrink-0 hover:bg-slate-100 active:bg-slate-200 flex items-center justify-center rounded-full transition-colors duration-200"
              onClick={onToggleSidebar}
            >
              <ChevronRight className="h-5 w-5" />
            </Button>
          </Tooltip>
        </div>

        {/* New conversation button */}
        <div className="py-1 flex justify-center">
          <Tooltip title={t("chatLeftSidebar.newConversation")} placement="right">
            <Button
              type="text"
              size="middle"
              className="h-10 w-10 min-w-[40px] p-0 flex-shrink-0 hover:bg-slate-100 active:bg-slate-200 flex items-center justify-center rounded-full transition-colors duration-200"
              onClick={conversationManagement.handleNewConversation}
            >
              <Plus className="h-5 w-5" />
            </Button>
          </Tooltip>
        </div>

        {/* Spacer */}
        <div className="flex-1" />
      </>
    );
  };

  return (
    <Layout.Sider
      collapsible
      collapsed={collapsed}
      onCollapse={setCollapsed}
      breakpoint="lg"
      width={260}
      collapsedWidth={40}
      trigger={null}
      theme="light"
      className="border-r border-transparent !bg-[rgb(242,248,255)] w-full"
    >
      {!collapsed ? (
        <div className="flex flex-col h-full w-full overflow-hidden space-between">
            <div className="m-4 mt-3">
              <div className="flex items-center gap-2">
                <Button
                  type="default"
                  size="middle"
                  className="flex-1 justify-start text-base overflow-hidden h-10 border border-slate-300 hover:border-slate-400 hover:bg-white transition-colors duration-200"
                  onClick={conversationManagement.handleNewConversation}
                >
                  <Plus
                    className="mr-2 flex-shrink-0"
                    style={{ height: "20px", width: "20px" }}
                  />
                  <span className="truncate">
                    {t("chatLeftSidebar.newConversation")}
                  </span>
                </Button>
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
              </div>
            </div>

            <div className="flex-1 min-h-0 p-3 pt-0 w-full flex flex-col overflow-hidden">
              <div className="flex-1 min-h-0 flex flex-col overflow-y-auto">
                <div className="flex flex-col gap-4 pb-4">
                  {conversationManagement.conversationList.length > 0 ? 
                  (
                    <>
                      {renderConversationList(today, t("chatLeftSidebar.today"))}
                      {renderConversationList(week, t("chatLeftSidebar.last7Days"))}
                      {renderConversationList(older, t("chatLeftSidebar.older"))}
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
              </div>
            </div>
          </div>
        ) : (
          renderCollapsedSidebar()
        )}
      <style jsx global>{`
        .chat-sidebar-title-fade {
          -webkit-mask-image: linear-gradient(
            to right,
            #000 0%,
            #000 88%,
            transparent 100%
          );
          mask-image: linear-gradient(
            to right,
            #000 0%,
            #000 88%,
            transparent 100%
          );
        }

        .group:hover .chat-sidebar-title-fade {
          -webkit-mask-image: linear-gradient(
            to right,
            #000 0%,
            #000 76%,
            transparent 100%
          );
          mask-image: linear-gradient(
            to right,
            #000 0%,
            #000 76%,
            transparent 100%
          );
        }
      `}</style>
    </Layout.Sider>
  );
}

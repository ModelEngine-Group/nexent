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

import { Button, Dropdown, Layout, Typography, Tooltip } from "antd";
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
  const [collapsed, setCollapsed] = useState(false);
  const [openDropdownId, setOpenDropdownId] = useState<number | null>(null);

  const onToggleSidebar = () => setCollapsed((prev) => !prev);

  const handleRenameClick = (conversationId: number) => {
    setEditingId(conversationId);
  };

  const handleRename = async (conversationId: number, newTitle: string) => {
    if (!newTitle.trim()) return;
    try {
      await conversationService.rename(conversationId, newTitle.trim());
      await conversationManagement.fetchConversationList();
      if (conversationManagement.selectedConversationId === conversationId) {
        conversationManagement.setConversationTitle(newTitle.trim());
      }
      setEditingId(null);
    } catch (error) {
      log.error(t("chatInterface.renameFailed"), error);
    }
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
        {conversation.map((conversation) => (
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
                title={
                  <span className="break-words max-w-[300px] block">
                    {conversation.conversation_title}
                  </span>
                }
                placement="bottom"
              >
                <div
                  className="flex items-center min-h-10 min-w-0 w-full px-3 py-2 cursor-pointer"
                  onClick={() => onConversationSelect(conversation)}
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
                  <Typography.Text
                    ellipsis={{ tooltip: false }}
                    editable={{
                      icon: null,
                      editing: editingId === conversation.conversation_id,
                      onChange: (value) => handleRename(conversation.conversation_id, value),
                      // onCancel: () => setEditingId(null),
                    }}
                    className="block text-base font-normal text-gray-800 tracking-wide font-sans ml-0.5 flex-1 min-w-0"
                  >
                    {conversation.conversation_title}
                  </Typography.Text>
                </div>
              </div>
            </Tooltip>
            </div>

            <div className={`shrink-0 w-9 flex items-center justify-center invisible group-hover:visible ${openDropdownId === conversation.conversation_id ? "!visible" : ""}`}>
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
                    handleRenameClick(conversation.conversation_id);
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
      width={240}
      collapsedWidth={40}
      trigger={null}
      theme="light"
      className="border-r border-transparent bg-primary/5 w-full"
    >
      {!collapsed ? (
        <div className="flex flex-col h-full w-full overflow-hidden">
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

            <div className="flex-1 min-h-0 p-2 w-full flex flex-col overflow-hidden">
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
        /* Hide editable icon and prevent tooltip on hover */
        .chat-sidebar-editable-title .ant-typography-edit {
          display: none !important;
        }
        /* Typography root: flex container for vertical center in edit mode */
        .chat-sidebar-editable-title .ant-typography {
          display: flex !important;
          align-items: center !important;
          align-self: center !important;
          flex: 1 !important;
          min-width: 0 !important;
        }
        /* Edit content wrapper: flex and center the textarea */
        .chat-sidebar-editable-title .ant-typography-edit-content {
          display: flex !important;
          align-items: center !important;
          align-self: center !important;
          flex: 1 !important;
          min-width: 0 !important;
          margin-left: 0.125rem !important;
          margin-top: 0 !important;
          margin-bottom: 0 !important;
          min-height: unset !important;
          position: static !important;
        }
        /* Input/textarea: match text style, no border, single line */
        .chat-sidebar-editable-title .ant-typography-edit-content .ant-input,
        .chat-sidebar-editable-title .ant-typography-edit-content textarea.ant-input {
          font-size: 1rem !important;
          line-height: 1.5rem !important;
          font-weight: 400 !important;
          color: rgb(31 41 55) !important;
          letter-spacing: 0.025em !important;
          font-family: ui-sans-serif, system-ui, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol", "Noto Color Emoji" !important;
          min-width: 0 !important;
          flex: 1 !important;
          padding: 0 !important;
          margin: 0 !important;
          border: none !important;
          border-radius: 0 !important;
          box-shadow: none !important;
          background: transparent !important;
          min-height: 1.5rem !important;
          height: 1.5rem !important;
          resize: none !important;
        }
        .chat-sidebar-editable-title .ant-typography-edit-content .ant-input:focus,
        .chat-sidebar-editable-title .ant-typography-edit-content textarea.ant-input:focus {
          box-shadow: none !important;
        }
      `}</style>
    </Layout.Sider>
  );
}

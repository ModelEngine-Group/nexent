import { useState, useRef, useEffect } from "react";
import {
  Clock,
  Plus,
  Pencil,
  Trash2,
  MoreHorizontal,
  ChevronLeft,
  ChevronRight,
  Trash,
} from "lucide-react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdownMenu";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { StaticScrollArea } from "@/components/ui/scrollArea";
import { USER_ROLES } from "@/const/modelConfig";
import { useTranslation } from "react-i18next";
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
  settingsMenuItems,
  onDropdownOpenChange,
  onToggleSidebar,
  expanded,
  userEmail,
  userAvatarUrl,
  userRole = USER_ROLES.USER,
}: ChatSidebarProps) {
  const { t } = useTranslation();
  const router = useRouter();
  const { today, week, older } = categorizeDialogs(conversationList);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  // Add delete dialog status
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const [dialogToDelete, setDialogToDelete] = useState<number | null>(null);
  
  // Add delete all dialog status
  const [isDeleteAllDialogOpen, setIsDeleteAllDialogOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

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
    setDialogToDelete(dialogId);
    setIsDeleteDialogOpen(true);
    // Close dropdown menus
    onDropdownOpenChange(false, null);
  };

  // Confirm delete
  const confirmDelete = () => {
    if (dialogToDelete !== null) {
      onDelete(dialogToDelete);
      setIsDeleteDialogOpen(false);
      setDialogToDelete(null);
    }
  };

  // Handle delete all click
  const handleDeleteAllClick = () => {
    if (conversationList.length > 0) {
      setIsDeleteAllDialogOpen(true);
    }
  };

  // Confirm delete all
  const confirmDeleteAll = async () => {
    setIsDeleting(true);
    try {
      for (const conv of conversationList) {
        await onDelete(conv.conversation_id);
      }
    } finally {
      setIsDeleting(false);
      setIsDeleteAllDialogOpen(false);
    }
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
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="ghost"
                        className="flex-1 justify-start text-left hover:bg-transparent min-w-0 max-w-[250px]"
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
                    </TooltipTrigger>
                    <TooltipContent side="right" className="max-w-xs">
                      <p className="break-words">{dialog.conversation_title}</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>

                <DropdownMenu
                  open={openDropdownId === dialog.conversation_id.toString()}
                  onOpenChange={(open) =>
                    onDropdownOpenChange(
                      open,
                      dialog.conversation_id.toString()
                    )
                  }
                >
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6 flex-shrink-0 opacity-0 group-hover:opacity-100 hover:bg-slate-100 hover:border hover:border-slate-200 mr-1 focus:outline-none focus:ring-0"
                    >
                      <MoreHorizontal className="h-4 w-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" side="bottom">
                    <DropdownMenuItem
                      onClick={() =>
                        handleStartEdit(
                          dialog.conversation_id,
                          dialog.conversation_title
                        )
                      }
                    >
                      <Pencil className="mr-2 h-5 w-5" />
                      {t("chatLeftSidebar.rename")}
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      className="text-red-500 hover:text-red-600 hover:bg-red-50"
                      onClick={() => handleDeleteClick(dialog.conversation_id)}
                    >
                      <Trash2 className="mr-2 h-5 w-5" />
                      {t("chatLeftSidebar.delete")}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
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
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-10 w-10 rounded-full hover:bg-slate-100"
                  onClick={onToggleSidebar}
                >
                  <ChevronRight className="h-6 w-6" strokeWidth={2.5} />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right">
                {t("chatLeftSidebar.expandSidebar")}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>

        {/* New conversation button */}
        <div className="py-3 flex justify-center">
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-10 w-10 rounded-full hover:bg-slate-100"
                  onClick={onNewConversation}
                >
                  <Plus className="h-6 w-6" strokeWidth={2.5} />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right">
                {t("chatLeftSidebar.newConversation")}
              </TooltipContent>
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
                  variant="outline"
                  className="flex-1 justify-start text-base overflow-hidden"
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
                    <TooltipTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-10 w-10 flex-shrink-0 hover:bg-slate-100"
                        onClick={onToggleSidebar}
                      >
                        <ChevronLeft className="h-5 w-5" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>{t("chatLeftSidebar.collapseSidebar")}</p>
                    </TooltipContent>
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
                    <Button variant="ghost" className="w-full justify-start">
                      <Clock className="mr-2 h-5 w-5" />
                      {t("chatLeftSidebar.noHistory")}
                    </Button>
                  </div>
                )}
              </div>
            </StaticScrollArea>

            {/* Delete all button */}
            {conversationList.length > 0 && (
              <div className="p-2 border-t border-slate-200">
                <Button
                  variant="ghost"
                  className="w-full justify-start text-red-500 hover:text-red-600 hover:bg-red-50"
                  onClick={handleDeleteAllClick}
                >
                  <Trash className="mr-2 h-4 w-4" />
                  {t("chatLeftSidebar.deleteAll", { defaultValue: "清空所有对话" })}
                </Button>
              </div>
            )}
          </div>
        ) : (
          renderCollapsedSidebar()
        )}
      </div>

      {/* Delete confirmation dialog */}
      <Dialog open={isDeleteDialogOpen} onOpenChange={setIsDeleteDialogOpen}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>
              {t("chatLeftSidebar.confirmDeletionTitle")}
            </DialogTitle>
            <DialogDescription>
              {t("chatLeftSidebar.confirmDeletionDescription")}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setIsDeleteDialogOpen(false)}
            >
              {t("chatLeftSidebar.cancel")}
            </Button>
            <Button variant="destructive" onClick={confirmDelete}>
              {t("chatLeftSidebar.delete")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete all confirmation dialog */}
      <Dialog open={isDeleteAllDialogOpen} onOpenChange={setIsDeleteAllDialogOpen}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>
              {t("chatLeftSidebar.confirmDeleteAllTitle", { defaultValue: "确认清空所有对话" })}
            </DialogTitle>
            <DialogDescription>
              {t("chatLeftSidebar.confirmDeleteAllDescription", { 
                defaultValue: `确定要删除全部 ${conversationList.length} 个对话吗？此操作不可恢复。`,
                count: conversationList.length 
              })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setIsDeleteAllDialogOpen(false)}
              disabled={isDeleting}
            >
              {t("chatLeftSidebar.cancel")}
            </Button>
            <Button 
              variant="destructive" 
              onClick={confirmDeleteAll}
              disabled={isDeleting}
            >
              {isDeleting 
                ? t("chatLeftSidebar.deleting", { defaultValue: "删除中..." })
                : t("chatLeftSidebar.deleteAll", { defaultValue: "清空全部" })
              }
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

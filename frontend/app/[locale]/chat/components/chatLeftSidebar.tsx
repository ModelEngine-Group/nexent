import { useState, useRef, useEffect } from "react";
import {
  Clock,
  Settings,
  Plus,
  Pencil,
  Trash2,
  MoreHorizontal,
  ChevronLeft,
  ChevronRight,
  User,
} from "lucide-react";

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
import { useConfig } from "@/hooks/useConfig";
import { useResponsiveTextSize } from "@/hooks/useResponsiveTextSize";
import { Spin, Tag, ConfigProvider } from "antd";
import { getRoleColor } from "@/lib/auth";
import { useAuth } from "@/hooks/useAuth";
import { extractColorsFromUri } from "@/lib/avatar";
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
  onDropdownOpenChange,
  onToggleSidebar,
  expanded,
  userEmail,
  userAvatarUrl,
  userRole = USER_ROLES.USER,
}: ChatSidebarProps) {
  const { t } = useTranslation();
  const { today, week, older } = categorizeDialogs(conversationList);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  // Get user authentication status
  const { isLoading: userAuthLoading, isSpeedMode } = useAuth();

  // Add delete dialog status
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const [dialogToDelete, setDialogToDelete] = useState<number | null>(null);

  // Use the configuration system to get the avatar content
  const { appConfig, getAppAvatarUrl } = useConfig();

  const sidebarAvatarUrl = getAppAvatarUrl(16); // The avatar size of the sidebar is 16
  const collapsedAvatarUrl = getAppAvatarUrl(16); // The avatar size of the collapsed state is 16

  // Calculate the container width (300px - icon width - button width - padding)
  const containerWidth = 300 - 40 - 40 - 40; // Approximately 180px available space

  // Use the responsive text size hook
  const { textRef, fontSize } = useResponsiveTextSize(
    appConfig.appName,
    containerWidth
  );

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

  // Render application icon
  const renderAppIcon = () => {
    return (
      <div className="h-8 w-8 rounded-full overflow-hidden mr-2">
        <img
          src={sidebarAvatarUrl}
          alt={appConfig.appName}
          className="h-full w-full object-cover"
        />
      </div>
    );
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
        {/* Application icon */}
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <div
                className="flex justify-start p-4 cursor-pointer"
                onClick={onToggleSidebar}
              >
                <div className="h-8 w-8 rounded-full overflow-hidden">
                  <img
                    src={collapsedAvatarUrl}
                    alt={appConfig.appName}
                    className="h-full w-full object-cover"
                  />
                </div>
              </div>
            </TooltipTrigger>
            <TooltipContent side="right">{appConfig.appName}</TooltipContent>
          </Tooltip>
        </TooltipProvider>

        <div className="flex flex-col flex-1 items-center">
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-14 w-14 rounded-full hover:bg-slate-100"
                  onClick={onToggleSidebar}
                >
                  <ChevronRight
                    className="h-6 w-6"
                    style={{ height: "28px", width: "28px" }}
                  />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right">
                {t("chatLeftSidebar.expandSidebar")}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>

          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-14 w-14 rounded-full hover:bg-slate-100"
                  onClick={onNewConversation}
                >
                  <Plus
                    className="h-6 w-6"
                    style={{ height: "20px", width: "20px" }}
                  />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right">
                {t("chatLeftSidebar.newConversation")}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>

        {/* Bottom area */}
        {userAuthLoading ? (
          <div className="py-2 flex justify-center">
            <div className="h-8 w-8 flex items-center justify-center">
              <Spin size="default" />
            </div>
          </div>
        ) : !isSpeedMode ? (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="py-2 flex justify-center cursor-pointer">
                  <div
                    className="h-8 w-8 rounded-full overflow-hidden"
                    style={{ backgroundColor: "#f0f2f5" }}
                  >
                    {userAvatarUrl ? (
                      <img
                        src={userAvatarUrl}
                        alt={userEmail || t("chatLeftSidebar.user")}
                        className="h-full w-full object-cover"
                      />
                    ) : (
                      <div className="h-full w-full bg-gray-200 flex items-center justify-center">
                        <User className="h-5 w-5" />
                      </div>
                    )}
                  </div>
                </div>
              </TooltipTrigger>
              {userEmail && (
                <TooltipContent side="right">{userEmail}</TooltipContent>
              )}
            </Tooltip>
          </TooltipProvider>
        ) : null}

        {/* Settings button */}
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="flex justify-center">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-10 w-10 rounded-full hover:bg-slate-100"
                  onClick={onSettingsClick}
                >
                  <Settings className="h-6 w-6" />
                </Button>
              </div>
            </TooltipTrigger>
            <TooltipContent side="right">
              {t("chatLeftSidebar.settings")}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </>
    );
  };

  const colors = extractColorsFromUri(appConfig.avatarUri || "");
  const mainColor = colors.mainColor || "273746";
  const secondaryColor = colors.secondaryColor || mainColor;

  return (
    <>
      <div
        className="hidden md:flex w-64 flex-col border-r border-transparent bg-primary/5 text-base transition-all duration-300 ease-in-out overflow-hidden"
        style={{ width: expanded ? "300px" : "70px" }}
      >
        {expanded || !animationComplete ? (
          <div className="hidden md:flex flex-col h-full overflow-hidden">
            <div className="p-2 border-b border-transparent">
              <div className="flex items-center p-2">
                <div
                  className="flex-1 min-w-0 flex items-center justify-start cursor-pointer"
                  onClick={onToggleSidebar}
                >
                  <div>{renderAppIcon()}</div>
                  <h1
                    ref={textRef}
                    className="font-semibold truncate bg-clip-text text-transparent"
                    style={{
                      fontSize: `${fontSize}px`,
                      backgroundImage: `linear-gradient(180deg, #${mainColor} 0%, #${secondaryColor} 100%)`,
                    }}
                  >
                    {appConfig.appName}
                  </h1>
                </div>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 flex-shrink-0 hover:bg-slate-100"
                        onClick={onToggleSidebar}
                      >
                        <ChevronLeft
                          className="h-7 w-7"
                          style={{ height: "28px", width: "28px" }}
                        />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>{t("chatLeftSidebar.collapseSidebar")}</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
            </div>

            <div className="m-4">
              <Button
                variant="outline"
                className="w-full justify-start text-base overflow-hidden"
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

            <div className="mt-auto p-3 border-t border-transparent flex justify-between items-center">
              {userAuthLoading ? (
                <div className="flex items-center">
                  <div className="h-8 w-8 mr-2 flex items-center justify-center">
                    <Spin size="default" />
                  </div>
                  <span className="text-sm font-medium text-slate-600 dark:text-slate-300">
                    {t("common.loading")}
                  </span>
                </div>
              ) : !isSpeedMode ? (
                <ConfigProvider getPopupContainer={() => document.body}>
                  <div className="flex items-center py-1 px-2">
                    <div className="h-8 w-8 rounded-full overflow-hidden mr-2">
                      {userAvatarUrl ? (
                        <img
                          src={userAvatarUrl}
                          alt={userEmail || t("chatLeftSidebar.user")}
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        <div className="h-full w-full bg-gray-200 flex items-center justify-center">
                          <User className="h-5 w-5" />
                        </div>
                      )}
                    </div>
                    <div className="flex flex-col overflow-hidden">
                      <TooltipProvider>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <div className="text-xs font-medium text-slate-600 dark:text-slate-300 truncate">
                              {userEmail || ""}
                            </div>
                          </TooltipTrigger>
                          {userEmail && (
                            <TooltipContent side="top">
                              {userEmail}
                            </TooltipContent>
                          )}
                        </Tooltip>
                      </TooltipProvider>
                      {userRole && (
                        <Tag
                          color={getRoleColor(userRole)}
                          className="mt-1 cursor-auto w-fit"
                        >
                          {t(userRole === "admin" ? "auth.admin" : "auth.user")}
                        </Tag>
                      )}
                    </div>
                  </div>
                </ConfigProvider>
              ) : null}
              <Button
                variant="ghost"
                size="icon"
                className="size-10 rounded-full hover:bg-slate-100"
                onClick={onSettingsClick}
              >
                <Settings className="size-5" />
              </Button>
            </div>
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
    </>
  );
}

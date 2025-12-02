"use client";

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { NavigationLayout } from "@/components/navigation/NavigationLayout";
import { HomepageContent } from "@/components/homepage/HomepageContent";
import { AuthDialogs } from "@/components/homepage/AuthDialogs";
import { LoginModal } from "@/components/auth/loginModal";
import { RegisterModal } from "@/components/auth/registerModal";
import { useAuth } from "@/hooks/useAuth";
import { ConfigProvider, App } from "antd";
import modelEngineService from "@/services/modelEngineService";
import { CONNECTION_STATUS, ConnectionStatus } from "@/const/modelConfig";
import log from "@/lib/logger";

// Import content components
import MemoryContent from "./memory/MemoryContent";
import ModelsContent from "./models/ModelsContent";
import AgentsContent from "./agents/AgentsContent";
import KnowledgesContent from "./knowledges/KnowledgesContent";
import { SpaceContent } from "./space/components/SpaceContent";
import { fetchAgentList } from "@/services/agentConfigService";
import { useAgentImport } from "@/hooks/useAgentImport";
import SetupLayout from "./setup/SetupLayout";
import { ChatContent } from "./chat/internal/ChatContent";
import { ChatTopNavContent } from "./chat/internal/ChatTopNavContent";
import { Badge, Button as AntButton } from "antd";
import { FiRefreshCw } from "react-icons/fi";
import { USER_ROLES } from "@/const/modelConfig";
import MarketContent from "./market/MarketContent";
import UsersContent from "./users/UsersContent";
import { getSavedView, saveView } from "@/lib/viewPersistence";

// View type definition
type ViewType = "home" | "memory" | "models" | "agents" | "knowledges" | "space" | "setup" | "chat" | "market" | "users";
type SetupStep = "models" | "knowledges" | "agents";

export default function Home() {
  const [mounted, setMounted] = useState(false);

  // Prevent hydration errors
  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return null;
  }

  return (
    <ConfigProvider getPopupContainer={() => document.body}>
      <FrontpageContent />
    </ConfigProvider>
  );

  function FrontpageContent() {
    const { t } = useTranslation("common");
    const { message } = App.useApp();
    const {
      user,
      isLoading: userLoading,
      openLoginModal,
      openRegisterModal,
      isSpeedMode,
    } = useAuth();
    const [loginPromptOpen, setLoginPromptOpen] = useState(false);
    const [adminRequiredPromptOpen, setAdminRequiredPromptOpen] =
      useState(false);
    
    // View state management with localStorage persistence
    const [currentView, setCurrentView] = useState<ViewType>(getSavedView);
    
    // Connection status for model-dependent views
    const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>(
      CONNECTION_STATUS.PROCESSING
    );
    const [isCheckingConnection, setIsCheckingConnection] = useState(false);
    
    // Space-specific states
    const [agents, setAgents] = useState<any[]>([]);
    const [isLoadingAgents, setIsLoadingAgents] = useState(false);
    const [isImporting, setIsImporting] = useState(false);
    
    // Setup-specific states
    const [currentSetupStep, setCurrentSetupStep] = useState<SetupStep>("models");
    const [isSaving, setIsSaving] = useState(false);

    // Handle operations that require login
    const handleAuthRequired = () => {
      if (!isSpeedMode && !user) {
        setLoginPromptOpen(true);
      }
    };

    // Confirm login dialog
    const handleCloseLoginPrompt = () => {
      setLoginPromptOpen(false);
    };

    // Handle login button click
    const handleLoginClick = () => {
      setLoginPromptOpen(false);
      openLoginModal();
    };

    // Handle register button click
    const handleRegisterClick = () => {
      setLoginPromptOpen(false);
      openRegisterModal();
    };

    // Handle operations that require admin privileges
    const handleAdminRequired = () => {
      if (!isSpeedMode && user?.role !== "admin") {
        setAdminRequiredPromptOpen(true);
      }
    };

    // Close admin prompt dialog
    const handleCloseAdminPrompt = () => {
      setAdminRequiredPromptOpen(false);
    };
    
    // Determine if user is admin
    const isAdmin = isSpeedMode || user?.role === USER_ROLES.ADMIN;
    
    // Load data for the saved view on initial mount
    useEffect(() => {
      if (currentView === "space" && agents.length === 0) {
        loadAgents();
      }
    }, []); // Only run on mount
    
    // Handle view change from navigation
    const handleViewChange = (view: string) => {
      const viewType = view as ViewType;
      setCurrentView(viewType);
      
      // Save current view to localStorage for persistence across page refreshes
      saveView(viewType);
      
      // Initialize setup step based on user role
      if (viewType === "setup") {
        if (isAdmin) {
          setCurrentSetupStep("models");
        } else {
          setCurrentSetupStep("knowledges");
        }
      }
      
      // Load data for specific views
      if (viewType === "space") {
        loadAgents(); // Always refresh agents when entering space
      }
    };
    
    // Check ModelEngine connection status
    const checkModelEngineConnection = async () => {
      setIsCheckingConnection(true);
      try {
        const result = await modelEngineService.checkConnection();
        setConnectionStatus(result.status);
      } catch (error) {
        log.error(t("setup.page.error.checkConnection"), error);
        setConnectionStatus(CONNECTION_STATUS.ERROR);
      } finally {
        setIsCheckingConnection(false);
      }
    };
    
    // Load agents for space view
    const loadAgents = async () => {
      setIsLoadingAgents(true);
      try {
        const result = await fetchAgentList();
        if (result.success) {
          setAgents(result.data);
        } else {
          message.error(t(result.message) || "Failed to load agents");
        }
      } catch (error) {
        log.error("Failed to load agents:", error);
        message.error("Failed to load agents");
      } finally {
        setIsLoadingAgents(false);
      }
    };
    
    // Use unified import hook for space view
    const { importFromFile: importAgentFile } = useAgentImport({
      onSuccess: () => {
        message.success(t("businessLogic.config.error.agentImportSuccess"));
        loadAgents();
        setIsImporting(false);
      },
      onError: (error) => {
        log.error(t("agentConfig.agents.importFailed"), error);
        message.error(t("businessLogic.config.error.agentImportFailed"));
        setIsImporting(false);
      },
    });

    // Handle import agent for space view
    const handleImportAgent = () => {
      const fileInput = document.createElement("input");
      fileInput.type = "file";
      fileInput.accept = ".json";
      fileInput.onchange = async (event) => {
        const file = (event.target as HTMLInputElement).files?.[0];
        if (!file) return;

        if (!file.name.endsWith(".json")) {
          message.error(t("businessLogic.config.error.invalidFileType"));
          return;
        }

        setIsImporting(true);
        try {
          await importAgentFile(file);
        } catch (error) {
          // Error already handled by hook's onError callback
        }
      };

      fileInput.click();
    };
    
    // Setup navigation handlers
    const handleSetupNext = () => {
      if (currentSetupStep === "models") {
        setCurrentSetupStep("knowledges");
      } else if (currentSetupStep === "knowledges") {
        if (isAdmin) {
          setCurrentSetupStep("agents");
        }
      }
    };

    const handleSetupBack = () => {
      if (currentSetupStep === "knowledges") {
        if (isAdmin) {
          setCurrentSetupStep("models");
        }
      } else if (currentSetupStep === "agents") {
        setCurrentSetupStep("knowledges");
      }
    };

    const handleSetupComplete = () => {
      setCurrentView("chat");
      saveView("chat");
    };
    
    // Determine setup button visibility based on current step and user role
    const getSetupNavigationProps = () => {
      if (!isAdmin) {
        return {
          showBack: false,
          showNext: false,
          showComplete: true,
        };
      }

      switch (currentSetupStep) {
        case "models":
          return {
            showBack: false,
            showNext: true,
            showComplete: false,
          };
        case "knowledges":
          return {
            showBack: true,
            showNext: true,
            showComplete: false,
          };
        case "agents":
          return {
            showBack: true,
            showNext: false,
            showComplete: true,
          };
        default:
          return {
            showBack: false,
            showNext: false,
            showComplete: false,
          };
      }
    };

    // Render content based on current view
    const renderContent = () => {
      switch (currentView) {
        case "home":
          return (
            <div className="w-full h-full flex items-center justify-center p-4">
              <HomepageContent
                onAuthRequired={handleAuthRequired}
                onAdminRequired={handleAdminRequired}
                onChatNavigate={() => {
                  setCurrentView("chat");
                  saveView("chat");
                }}
                onSetupNavigate={() => {
                  setCurrentView("setup");
                  saveView("setup");
                }}
                onSpaceNavigate={() => {
                  setCurrentView("space");
                  saveView("space");
                }}
              />
            </div>
          );
        
        case "memory":
          return (
            <div className="w-full h-full p-1">
              <MemoryContent />
            </div>
          );
        
        case "models":
          return (
            <div className="w-full h-full p-8">
              <ModelsContent
                connectionStatus={connectionStatus}
                isCheckingConnection={isCheckingConnection}
                onCheckConnection={checkModelEngineConnection}
              />
            </div>
          );
        
        case "agents":
          return (
            <div className="w-full h-full p-8">
              <AgentsContent
                connectionStatus={connectionStatus}
                isCheckingConnection={isCheckingConnection}
                onCheckConnection={checkModelEngineConnection}
              />
            </div>
          );
        
        case "knowledges":
          return (
            <div className="w-full h-full p-8">
              <KnowledgesContent
                isSaving={false}
                connectionStatus={connectionStatus}
                isCheckingConnection={isCheckingConnection}
                onCheckConnection={checkModelEngineConnection}
              />
            </div>
          );
        
        case "space":
          return (
            <SpaceContent
              agents={agents}
              isLoading={isLoadingAgents}
              isImporting={isImporting}
              onRefresh={loadAgents}
              onLoadAgents={loadAgents}
              onImportAgent={handleImportAgent}
              onChatNavigate={(agentId) => {
                // Update URL with agent_id parameter for auto-selection in ChatAgentSelector
                const url = new URL(window.location.href);
                url.searchParams.set("agent_id", agentId);
                window.history.replaceState({}, "", url.toString());
                
                setCurrentView("chat");
                saveView("chat");
              }}
              onEditNavigate={() => {
                // Navigate to agents development view
                setCurrentView("agents");
                saveView("agents");
              }}
            />
          );
        
        case "chat":
          return <ChatContent />;
        
        case "market":
          return (
            <div className="w-full h-full">
              <MarketContent
                connectionStatus={connectionStatus}
                isCheckingConnection={isCheckingConnection}
                onCheckConnection={checkModelEngineConnection}
              />
            </div>
          );
        
        case "users":
          return (
            <div className="w-full h-full">
              <UsersContent
                connectionStatus={connectionStatus}
                isCheckingConnection={isCheckingConnection}
                onCheckConnection={checkModelEngineConnection}
              />
            </div>
          );
        
        case "setup":
          const setupNavProps = getSetupNavigationProps();
          return (
            <SetupLayout
              onBack={handleSetupBack}
              onNext={handleSetupNext}
              onComplete={handleSetupComplete}
              isSaving={isSaving}
              showBack={setupNavProps.showBack}
              showNext={setupNavProps.showNext}
              showComplete={setupNavProps.showComplete}
              nextText={t("setup.navigation.button.next")}
              completeText={t("setup.navigation.button.complete")}
            >
              {currentSetupStep === "models" && isAdmin && (
                <ModelsContent
                  onNext={handleSetupNext}
                  connectionStatus={connectionStatus}
                  isCheckingConnection={isCheckingConnection}
                  onCheckConnection={checkModelEngineConnection}
                />
              )}

              {currentSetupStep === "knowledges" && (
                <KnowledgesContent
                  isSaving={isSaving}
                  connectionStatus={connectionStatus}
                  isCheckingConnection={isCheckingConnection}
                  onCheckConnection={checkModelEngineConnection}
                  onSavingStateChange={setIsSaving}
                />
              )}

              {currentSetupStep === "agents" && isAdmin && (
                <AgentsContent
                  isSaving={isSaving}
                  connectionStatus={connectionStatus}
                  isCheckingConnection={isCheckingConnection}
                  onCheckConnection={checkModelEngineConnection}
                  onSavingStateChange={setIsSaving}
                />
              )}
            </SetupLayout>
          );
        
        default:
          return null;
      }
    };

    // Get status text for connection badge
    const getStatusText = () => {
      switch (connectionStatus) {
        case CONNECTION_STATUS.SUCCESS:
          return t("setup.header.status.connected");
        case CONNECTION_STATUS.ERROR:
          return t("setup.header.status.disconnected");
        case CONNECTION_STATUS.PROCESSING:
          return t("setup.header.status.checking");
        default:
          return t("setup.header.status.unknown");
      }
    };
    
    // Render status badge for setup view
    const renderStatusBadge = () => (
      <div className="flex items-center px-2 py-1 rounded-md border border-slate-200 dark:border-slate-700">
        <Badge
          status={connectionStatus}
          text={getStatusText()}
          className="[&>.ant-badge-status-dot]:w-[6px] [&>.ant-badge-status-dot]:h-[6px] [&>.ant-badge-status-text]:text-xs [&>.ant-badge-status-text]:ml-1.5 [&>.ant-badge-status-text]:font-medium"
        />
        <AntButton
          icon={
            <FiRefreshCw
              className={`h-3.5 w-3.5 ${isCheckingConnection ? "animate-spin" : ""}`}
            />
          }
          size="small"
          type="text"
          onClick={checkModelEngineConnection}
          disabled={isCheckingConnection}
          className="ml-1.5 !p-0 !h-auto !min-w-0"
        />
      </div>
    );

    return (
      <NavigationLayout
        onAuthRequired={handleAuthRequired}
        onAdminRequired={handleAdminRequired}
        onViewChange={handleViewChange}
        currentView={currentView}
        showFooter={currentView !== "setup"}
        contentMode={
          currentView === "home"
            ? "centered"
            : currentView === "memory" ||
              currentView === "models" ||
              currentView === "knowledges"
            ? "centered"
            : currentView === "chat"
            ? "fullscreen"
            : "scrollable"
        }
        topNavbarAdditionalTitle={
          currentView === "chat" ? <ChatTopNavContent /> : undefined
        }
        topNavbarAdditionalRightContent={
          currentView === "setup" ? renderStatusBadge() : undefined
        }
      >
        {renderContent()}

        {/* Auth dialogs - only shown in full version */}
        {!isSpeedMode && (
          <>
            <AuthDialogs
              loginPromptOpen={loginPromptOpen}
              adminPromptOpen={adminRequiredPromptOpen}
              onCloseLoginPrompt={handleCloseLoginPrompt}
              onCloseAdminPrompt={handleCloseAdminPrompt}
              onLoginClick={() => {
                setLoginPromptOpen(false);
                setAdminRequiredPromptOpen(false);
                openLoginModal();
              }}
              onRegisterClick={() => {
                setLoginPromptOpen(false);
                setAdminRequiredPromptOpen(false);
                openRegisterModal();
              }}
            />
            <LoginModal />
            <RegisterModal />
          </>
        )}
      </NavigationLayout>
    );
  }
}

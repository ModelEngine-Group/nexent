"use client";

import { useState, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
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
import SaveConfirmModal from "./agents/components/SaveConfirmModal";
import { SpaceContent } from "./space/components/SpaceContent";
import { fetchAgentList } from "@/services/agentConfigService";
import { useAgentImport, ImportAgentData } from "@/hooks/useAgentImport";
import SetupLayout from "./setup/SetupLayout";
import AgentImportWizard from "@/components/agent/AgentImportWizard";
import { ChatContent } from "./chat/internal/ChatContent";
import { ChatTopNavContent } from "./chat/internal/ChatTopNavContent";
import { Badge, Button as AntButton } from "antd";
import { RefreshCw } from "lucide-react";
import { USER_ROLES } from "@/const/modelConfig";
import MarketContent from "./market/MarketContent";
import UsersContent from "./users/UsersContent";
import McpToolsContent from "./mcp-tools/McpToolsContent";
import MonitoringContent from "./monitoring/MonitoringContent";
import { getSavedView, saveView } from "@/lib/viewPersistence";

// View type definition
type ViewType =
  | "home"
  | "memory"
  | "models"
  | "agents"
  | "knowledges"
  | "space"
  | "setup"
  | "chat"
  | "market"
  | "users"
  | "mcpTools"
  | "monitoring";
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
    
    // Agent import wizard states
    const [importWizardVisible, setImportWizardVisible] = useState(false);
    const [importWizardData, setImportWizardData] = useState<ImportAgentData | null>(null);
    
    // Setup-specific states
    const [currentSetupStep, setCurrentSetupStep] = useState<SetupStep>("models");
    const [isSaving, setIsSaving] = useState(false);
    
    // Agent save confirmation states
    const [showAgentSaveConfirm, setShowAgentSaveConfirm] = useState(false);
    const [pendingCompleteAction, setPendingCompleteAction] = useState<(() => void) | null>(null);
    const agentConfigRef = useRef<any>(null);

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
    const { importFromData } = useAgentImport({
      onSuccess: () => {
        message.success(t("businessLogic.config.error.agentImportSuccess"));
        loadAgents();
        setIsImporting(false);
        setImportWizardVisible(false);
        setImportWizardData(null);
      },
      onError: (error) => {
        log.error(t("agentConfig.agents.importFailed"), error);
        message.error(t("businessLogic.config.error.agentImportFailed"));
        setIsImporting(false);
      },
    });

    // Handle import agent for space view - open wizard instead of direct import
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

        try {
          // Read and parse file
          const fileContent = await file.text();
          let agentData: ImportAgentData;
          
          try {
            agentData = JSON.parse(fileContent);
          } catch (parseError) {
            message.error(t("businessLogic.config.error.invalidFileType"));
            return;
          }

          // Validate structure
          if (!agentData.agent_id || !agentData.agent_info) {
            message.error(t("businessLogic.config.error.invalidFileType"));
            return;
          }

          // Open wizard with parsed data
          setImportWizardData(agentData);
          setImportWizardVisible(true);
        } catch (error) {
          log.error("Failed to read import file:", error);
          message.error(t("businessLogic.config.error.agentImportFailed"));
        }
      };

      fileInput.click();
    };

    // Handle import completion from wizard
    // Note: AgentImportWizard already handles the import internally,
    // so we just need to refresh the agent list
    const handleImportComplete = () => {
      loadAgents();
      setImportWizardVisible(false);
      setImportWizardData(null);
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
      // Check if we're on the agents step and if there are unsaved changes
      if (currentSetupStep === "agents" && isAdmin && agentConfigRef.current) {
        if (agentConfigRef.current.hasUnsavedChanges?.()) {
          // Show save confirmation modal
          setShowAgentSaveConfirm(true);
          setPendingCompleteAction(() => () => {
            setCurrentView("chat");
            saveView("chat");
          });
          return;
        }
      }
      
      // No unsaved changes, proceed directly
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
            <>
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
            <AgentImportWizard
              visible={importWizardVisible}
              onCancel={() => {
                setImportWizardVisible(false);
                setImportWizardData(null);
              }}
              initialData={importWizardData}
              onImportComplete={handleImportComplete}
              title={undefined} // Use default title
              agentDisplayName={
                importWizardData?.agent_info?.[String(importWizardData.agent_id)]?.display_name
              }
              agentDescription={
                importWizardData?.agent_info?.[String(importWizardData.agent_id)]?.description
              }
            />
          </>
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

        case "mcpTools":
          return (
            <div className="w-full h-full p-8">
              <McpToolsContent
                connectionStatus={connectionStatus}
                isCheckingConnection={isCheckingConnection}
                onCheckConnection={checkModelEngineConnection}
              />
            </div>
          );

        case "monitoring":
          return (
            <div className="w-full h-full p-8">
              <MonitoringContent
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
                  ref={agentConfigRef}
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
            <RefreshCw
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
        showFooter={true}
        contentMode={
          currentView === "home"
            ? "centered"
            : currentView === "memory" ||
              currentView === "models" ||
              currentView === "knowledges" ||
              currentView === "setup"
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

        {/* Agent save confirmation modal for setup completion */}
        <SaveConfirmModal
          open={showAgentSaveConfirm}
          onCancel={async () => {
            // Reload data from backend to discard changes
            await agentConfigRef.current?.reloadCurrentAgentData?.();
            setShowAgentSaveConfirm(false);
            const action = pendingCompleteAction;
            setPendingCompleteAction(null);
            if (action) action();
          }}
          onSave={async () => {
            try {
              setIsSaving(true);
              await agentConfigRef.current?.saveAllChanges?.();
              setShowAgentSaveConfirm(false);
              const action = pendingCompleteAction;
              setPendingCompleteAction(null);
              if (action) action();
            } catch (e) {
              // errors are surfaced by underlying save
            } finally {
              setIsSaving(false);
            }
          }}
          onClose={() => {
            setShowAgentSaveConfirm(false);
            setPendingCompleteAction(null);
          }}
        />
      </NavigationLayout>
    );
  }
}

"use client"

import React, { useState, useEffect, ReactNode } from "react"
import { useRouter } from "next/navigation"
import { Modal, App, Button, Badge, Dropdown } from "antd"
import { WarningFilled, DownOutlined } from "@ant-design/icons"
import { motion, AnimatePresence } from "framer-motion"
import { FiRefreshCw, FiArrowLeft } from "react-icons/fi"
import { Globe } from "lucide-react"
import AppModelConfig from "./modelSetup/config"
import DataConfig from "./knowledgeSetup/config"
import AgentConfig from "./agentSetup/config"
import { configStore } from "@/lib/config"
import { configService } from "@/services/configService"
import modelEngineService, { ConnectionStatus } from "@/services/modelEngineService"
import { useAuth } from "@/hooks/useAuth"
import { useTranslation } from 'react-i18next'
import { languageOptions } from '@/lib/constants'
import { useLanguageSwitch } from '@/lib/languageUtils'
import { HEADER_CONFIG } from '@/lib/layoutConstants'


// ================ Header ================
interface HeaderProps {
  connectionStatus: "success" | "error" | "processing";
  isCheckingConnection: boolean;
  onCheckConnection: () => void;
}

function Header({
  connectionStatus,
  isCheckingConnection,
  onCheckConnection
}: HeaderProps) {
  const router = useRouter()
  const { t } = useTranslation()
  const { currentLanguage, handleLanguageChange } = useLanguageSwitch()

  // Get status text
  const getStatusText = () => {
    switch (connectionStatus) {
      case "success":
        return t("setup.header.status.connected")
      case "error":
        return t("setup.header.status.disconnected")
      case "processing":
        return t("setup.header.status.checking")
      default:
        return t("setup.header.status.unknown")
    }
  }

  return (
    <header className="w-full py-4 px-6 flex items-center justify-between border-b border-slate-200 dark:border-slate-700 bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm" style={{ height: HEADER_CONFIG.HEIGHT }}>
      <div className="flex items-center">
        <button
          onClick={() => router.push("/")}
          className="mr-3 p-2 rounded-full hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
          aria-label={t("setup.header.button.back")}
        >
          <FiArrowLeft className="text-slate-600 dark:text-slate-300 text-xl" />
        </button>
        <h1 className="text-xl font-bold text-blue-600 dark:text-blue-500">{t("setup.header.title")}</h1>
        <div className="mx-2 h-6 border-l border-slate-300 dark:border-slate-600"></div>
        <span className="text-slate-600 dark:text-slate-400 text-sm">{t("setup.header.description")}</span>
      </div>
      {/* 语言切换 */}
      <div className="flex items-center gap-3">
        <Dropdown
          menu={{
            items: languageOptions.map(opt => ({ key: opt.value, label: opt.label })),
            onClick: ({ key }) => handleLanguageChange(key as string),
          }}
        >
          <a
            className="ant-dropdown-link text-sm !font-medium text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white transition-colors flex items-center gap-2 cursor-pointer w-[110px] border-0 shadow-none bg-transparent text-left"
          >
            <Globe className="h-4 w-4" />
            {languageOptions.find(o => o.value === currentLanguage)?.label || currentLanguage}
            <DownOutlined className="text-[10px]" />
          </a>
        </Dropdown>
        {/* ModelEngine连通性状态 */}
        <div className="flex items-center px-3 py-1.5 rounded-md border border-slate-200 dark:border-slate-700">
          <Badge
            status={connectionStatus}
            text={getStatusText()}
            className="[&>.ant-badge-status-dot]:w-[8px] [&>.ant-badge-status-dot]:h-[8px] [&>.ant-badge-status-text]:text-base [&>.ant-badge-status-text]:ml-2 [&>.ant-badge-status-text]:font-medium"
          />
          <Button
            icon={<FiRefreshCw className={isCheckingConnection ? "animate-spin" : ""} />}
            size="small"
            type="text"
            onClick={onCheckConnection}
            disabled={isCheckingConnection}
            className="ml-2"
          />
        </div>
      </div>
    </header>
  )
}

// ================ Navigation ================
interface NavigationProps {
  selectedKey: string;
  onBackToFirstPage: () => void;
  onCompleteConfig: () => void;
  isSavingConfig: boolean;
  userRole?: "user" | "admin";
}

function Navigation({
  selectedKey,
  onBackToFirstPage,
  onCompleteConfig,
  isSavingConfig,
  userRole,
}: NavigationProps) {
  const { t } = useTranslation()

  return (
    <div className="mt-3 flex justify-between px-6">
      <div className="flex gap-2">
        {selectedKey != "1" && userRole === "admin" && (
          <button
            onClick={onBackToFirstPage}
            className={"px-6 py-2.5 rounded-md flex items-center text-sm font-medium bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 cursor-pointer transition-colors"}
          >
            {t("setup.navigation.button.previous")}
          </button>
        )}
      </div>

      <div className="flex gap-2">
        <button
          onClick={onCompleteConfig}
          disabled={isSavingConfig}
          className={"px-6 py-2.5 rounded-md flex items-center text-sm font-medium bg-blue-600 dark:bg-blue-600 text-white hover:bg-blue-700 dark:hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"}
          style={{ border: "none", marginLeft: selectedKey === "1" || userRole !== "admin" ? "auto" : undefined }}
        >
          {selectedKey === "3" ? (isSavingConfig ? t("setup.navigation.button.saving") : t("setup.navigation.button.complete")) :
           selectedKey === "2" && userRole !== "admin" ? (isSavingConfig ? t("setup.navigation.button.saving") : t("setup.navigation.button.complete")) :
           t("setup.navigation.button.next")}
        </button>
      </div>
    </div>
  )
}

// ================ Layout ================
interface LayoutProps {
  children: ReactNode;
  connectionStatus: "success" | "error" | "processing";
  isCheckingConnection: boolean;
  onCheckConnection: () => void;
  selectedKey: string;
  onBackToFirstPage: () => void;
  onCompleteConfig: () => void;
  isSavingConfig: boolean;
  userRole?: "user" | "admin";
}

function Layout({
  children,
  connectionStatus,
  isCheckingConnection,
  onCheckConnection,
  selectedKey,
  onBackToFirstPage,
  onCompleteConfig,
  isSavingConfig,
  userRole,
}: LayoutProps) {
  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-900 font-sans">
      <Header
        connectionStatus={connectionStatus}
        isCheckingConnection={isCheckingConnection}
        onCheckConnection={onCheckConnection}
      />

      {/* Main content */}
      <div className="max-w-[1800px] mx-auto px-8 pb-4 mt-6 bg-transparent">
          {children}
          <Navigation
            selectedKey={selectedKey}
            onBackToFirstPage={onBackToFirstPage}
            onCompleteConfig={onCompleteConfig}
            isSavingConfig={isSavingConfig}
            userRole={userRole}
          />
      </div>
    </div>
  )
}

export default function CreatePage() {
  const { message } = App.useApp();
  const [selectedKey, setSelectedKey] = useState("1")
  const router = useRouter()
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("processing")
  const [isCheckingConnection, setIsCheckingConnection] = useState(false)
  const [isSavingConfig, setIsSavingConfig] = useState(false)
  const [isFromSecondPage, setIsFromSecondPage] = useState(false)
  const { user, isLoading: userLoading, openLoginModal } = useAuth()
  const { modal } = App.useApp()
  const { t } = useTranslation()
  const [embeddingModalOpen, setEmbeddingModalOpen] = useState(false);
  const [pendingJump, setPendingJump] = useState(false);
  const [liveSelectedModels, setLiveSelectedModels] = useState<Record<string, Record<string, string>> | null>(null);


  // Check login status and permission
  useEffect(() => {
    if (!userLoading) {
      if (!user) {
        // user not logged in, do nothing
        return
      }

      // If the user is not an admin and currently on the first page, automatically jump to the second page
      if (user.role !== "admin" && selectedKey === "1") {
        setSelectedKey("2")
      }

      // If the user is not an admin and currently on the third page, force jump to the second page
      if (user.role !== "admin" && selectedKey === "3") {
        setSelectedKey("2")
      }
    }
  }, [user, userLoading, selectedKey, modal, openLoginModal, router])

  // Check the connection status when the page is initialized
  useEffect(() => {
    // Trigger knowledge base data acquisition only when the page is initialized
    window.dispatchEvent(new CustomEvent('knowledgeBaseDataUpdated', {
      detail: { forceRefresh: true }
    }))

    // Load config for normal user
    const loadConfigForNormalUser = async () => {
      if (user && user.role !== "admin") {
        try {
          await configService.loadConfigToFrontend()
          configStore.reloadFromStorage()
        } catch (error) {
          console.error("加载配置失败:", error)
        }
      }
    }

    loadConfigForNormalUser()

    // Check if the knowledge base configuration option card needs to be displayed
    const showPageConfig = localStorage.getItem('show_page')
    if (showPageConfig) {
      setSelectedKey(showPageConfig)
      localStorage.removeItem('show_page')
    }
  }, [user])

  // Listen for changes in selectedKey, refresh knowledge base data when entering the second page
  useEffect(() => {
    if (selectedKey === "2") {
      // When entering the second page, reset the flag
      setIsFromSecondPage(false)
      // Clear all possible caches
      localStorage.removeItem('preloaded_kb_data');
      localStorage.removeItem('kb_cache');
      // When entering the second page, get the latest knowledge base data
      // Use setTimeout to ensure the component is fully mounted before triggering the event
      setTimeout(() => {
        window.dispatchEvent(new CustomEvent('knowledgeBaseDataUpdated', {
          detail: { forceRefresh: true }
        }))
      }, 100)
    }
    checkModelEngineConnection()
  }, [selectedKey])

  // Function to check the ModelEngine connection status
  const checkModelEngineConnection = async () => {
    setIsCheckingConnection(true)

    try {
      const result = await modelEngineService.checkConnection()
      setConnectionStatus(result.status)
    } catch (error) {
      console.error(t('setup.page.error.checkConnection'), error)
      setConnectionStatus("error")
    } finally {
      setIsCheckingConnection(false)
    }
  }

  // Calculate the effective selectedKey, ensure that non-admin users get the correct page status
  const getEffectiveSelectedKey = () => {
    if (!user) return selectedKey;

    if (user.role !== "admin") {
      // If the current page is the first or third page, return the second page
      if (selectedKey === "1" || selectedKey === "3") {
        return "2";
      }
    }

    return selectedKey;
  };

  const renderContent = () => {
    // If the user is not an admin and attempts to access the first page, force display the second page content
    if (user?.role !== "admin" && selectedKey === "1") {
      return <DataConfig />
    }

    // If the user is not an admin and attempts to access the third page, force display the second page content
    if (user?.role !== "admin" && selectedKey === "3") {
      return <DataConfig />
    }

    switch (selectedKey) {
      case "1":
        return (
          <AppModelConfig
            skipModelVerification={isFromSecondPage}
            onSelectedModelsChange={(selected) => setLiveSelectedModels(selected)}
          />
        )
      case "2":
        return <DataConfig isActive={selectedKey === "2"} />
      case "3":
        return <AgentConfig />
      default:
        return null
    }
  }

  // Animation variants for smooth transitions
  const pageVariants = {
    initial: {
      opacity: 0,
      x: 20,
    },
    in: {
      opacity: 1,
      x: 0,
    },
    out: {
      opacity: 0,
      x: -20,
    },
  };

  const pageTransition = {
    type: "tween" as const,
    ease: "anticipate" as const,
    duration: 0.4,
  };

  // Handle completed configuration
  const handleCompleteConfig = async () => {
    if (selectedKey === "3") {
      // jump to chat page directly, no any check
      router.push("/chat")
    } else if (selectedKey === "2") {
      // If the user is an admin, jump to the third page; if the user is a normal user, complete the configuration directly and jump to the chat page
      if (user?.role === "admin") {
        setSelectedKey("3")
      } else {
        // Normal users complete the configuration directly on the second page
        try {
          setIsSavingConfig(true)

          // Reload the config for normal user before saving, ensure the latest model config
          await configService.loadConfigToFrontend()
          configStore.reloadFromStorage()

          // Get the current global configuration
          const currentConfig = configStore.getConfig()

          // Check if the main model is configured
          if (!currentConfig.models.llm.modelName) {
            message.error("未找到模型配置，请联系管理员先完成模型配置")
            return
          }

          router.push("/chat")

        } catch (error) {
          console.error("保存配置异常:", error)
          message.error("系统异常，请稍后重试")
        } finally {
          setIsSavingConfig(false)
        }
      }
      } else if (selectedKey === "1") {
      // Validate required fields when jumping from the first page to the second page
      try {
        // Get the current configuration
        const currentConfig = configStore.getConfig()

        // Check the main model
        if (!currentConfig.models.llm.modelName) {
          message.error(t('setup.page.error.selectMainModel'))

          // Trigger a custom event to notify the ModelConfigSection to mark the main model dropdown as an error
          window.dispatchEvent(new CustomEvent('highlightMissingField', {
            detail: { field: t('setup.page.error.highlightField.llmMain') }
          }))

          return
        }

        // check embedding model using live selection from current UI, not the stored config
        const hasEmbeddingLive = !!(liveSelectedModels?.embedding?.embedding) || !!(liveSelectedModels?.embedding?.multi_embedding)
        if (!hasEmbeddingLive) {
          setEmbeddingModalOpen(true);
          setPendingJump(true);
          // highlight embedding dropdown
          window.dispatchEvent(new CustomEvent('highlightMissingField', {
            detail: { field: 'embedding.embedding' }
          }))
          return;
        }

        // All required fields have been filled, allow the jump to the second page
        setSelectedKey("2")

        // Call the backend save configuration API
        await configService.saveConfigToBackend(currentConfig)
      } catch (error) {
        console.error(t('setup.page.error.systemError'), error)
        message.error(t('setup.page.error.systemError'))
      }
    }
  }

  // Handle the logic of the user switching to the first page
  const handleBackToFirstPage = () => {
    if (selectedKey === "3") {
      setSelectedKey("2")
    } else if (selectedKey === "2") {
      // Only admins can return to the first page
      if (user?.role !== "admin") {
        message.error(t('setup.page.error.adminOnly'))
        return
      }
      setSelectedKey("1")
      // Set the flag to indicate that the user is returning from the second page to the first page
      setIsFromSecondPage(true)
    }
  }

  const handleEmbeddingOk = async () => {
    setEmbeddingModalOpen(false)
    if (pendingJump) {
      setPendingJump(false)
      const currentConfig = configStore.getConfig()
      try {
        await configService.saveConfigToBackend(currentConfig)
      } catch (e) {
        message.error(t('setup.page.error.saveConfig'))
      }
      setSelectedKey("2")
    }
  }

  return (
    <Layout
      connectionStatus={connectionStatus}
      isCheckingConnection={isCheckingConnection}
      onCheckConnection={checkModelEngineConnection}
      selectedKey={getEffectiveSelectedKey()}
      onBackToFirstPage={handleBackToFirstPage}
      onCompleteConfig={handleCompleteConfig}
      isSavingConfig={isSavingConfig}
      userRole={user?.role}
    >
      <AnimatePresence
        mode="wait"
        onExitComplete={() => {
          // when animation is complete and switch to the second page, ensure the knowledge base data is updated
          if (selectedKey === "2") {
            setTimeout(() => {
              window.dispatchEvent(new CustomEvent('knowledgeBaseDataUpdated', {
                detail: { forceRefresh: true }
              }))
            }, 50)
          }
        }}
      >
        <motion.div
          key={selectedKey}
          initial="initial"
          animate="in"
          exit="out"
          variants={pageVariants}
          transition={pageTransition}
          style={{ width: '100%', height: '100%' }}
        >
          {renderContent()}
        </motion.div>
      </AnimatePresence>
      <Modal
        title={t('embedding.emptyWarningModal.title')}
        open={embeddingModalOpen}
        onCancel={() => setEmbeddingModalOpen(false)}
        centered
        footer={
          <div className="flex justify-end mt-6 gap-4">
            <Button onClick={handleEmbeddingOk}>
              {t('embedding.emptyWarningModal.ok_continue')}
            </Button>
            <Button type="primary" onClick={() => setEmbeddingModalOpen(false)}>
              {t('embedding.emptyWarningModal.cancel')}
            </Button>
          </div>
        }
      >
        <div className="py-2">
          <div className="flex items-center">
            <WarningFilled className="text-yellow-500 mt-1 mr-2" style={{ fontSize: "48px" }} />
            <div className="ml-3 mt-2">
              <div dangerouslySetInnerHTML={{ __html: t('embedding.emptyWarningModal.content') }} />
              <div className="mt-2 text-xs opacity-70">{t('embedding.emptyWarningModal.tip')}</div>
            </div>
          </div>
        </div>
      </Modal>
    </Layout>
  )
}
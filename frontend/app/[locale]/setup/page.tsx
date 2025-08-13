"use client"

import React, { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import { theme, Modal, App } from "antd"
import { ExclamationCircleFilled, ExclamationCircleOutlined } from "@ant-design/icons"
import { motion, AnimatePresence } from "framer-motion"
import AppModelConfig from "./modelSetup/config"
import DataConfig from "./knowledgeBaseSetup/KnowledgeBaseManager"
import AgentConfig from "./agentSetup/AgentConfig"
import { configStore } from "@/lib/config"
import { configService } from "@/services/configService"
import modelEngineService, { ConnectionStatus } from "@/services/modelEngineService"
import { useAuth } from "@/hooks/useAuth"
import Layout from "./layout"
import { useTranslation } from 'react-i18next'
import { userConfigService } from "@/services/userConfigService"
import { useKnowledgeBaseContext } from "./knowledgeBaseSetup/knowledgeBase/KnowledgeBaseContext"
import { KnowledgeBase } from "@/types/knowledgeBase"
import { API_ENDPOINTS } from "@/services/api"
import { getAuthHeaders } from '@/lib/auth'
import { useTheme } from 'next-themes';


export default function CreatePage() {
  const { message } = App.useApp();
  const [selectedKey, setSelectedKey] = useState("1")
  const router = useRouter()
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("processing")
  const [isCheckingConnection, setIsCheckingConnection] = useState(false)
  const [lastChecked, setLastChecked] = useState<string | null>(null)
  const [isSavingConfig, setIsSavingConfig] = useState(false)
  const [isFromSecondPage, setIsFromSecondPage] = useState(false)
  const { user, isLoading: userLoading, openLoginModal } = useAuth()
  const { modal } = App.useApp()
  const { state: { knowledgeBases, selectedIds }, saveUserSelectedKnowledgeBases } = useKnowledgeBaseContext()
  const { t } = useTranslation()
  const [embeddingModalOpen, setEmbeddingModalOpen] = useState(false);
  const [pendingJump, setPendingJump] = useState(false);
  const { token } = theme.useToken ? theme.useToken() : { token: {} };
  const { resolvedTheme } = typeof useTheme === 'function' ? useTheme() : { resolvedTheme: 'light' };
  const isDark = resolvedTheme === 'dark';


  // Check login status and permission
  useEffect(() => {
    if (!userLoading) {
      if (!user) {
        // user not logged in, show login prompt
        modal.confirm({
          title: t('login.expired.title'),
          icon: <ExclamationCircleOutlined />,
          content: t('login.expired.content'),
          okText: t('login.expired.okText'),
          cancelText: t('login.expired.cancelText'),
          closable: false,
          onOk() {
            openLoginModal();
          },
          onCancel() {
            router.push('/');
          }
        });
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
          await configStore.reloadFromStorage()
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
      // 使用 setTimeout 确保组件完全挂载后再触发事件
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
      setLastChecked(result.lastChecked)
    } catch (error) {
      console.error(t('setup.page.error.checkConnection'), error)
      setConnectionStatus("error")
    } finally {
      setIsCheckingConnection(false)
    }
  }

  // Add a function to display the number of selected knowledge bases
  const getSelectedKnowledgeBasesInfo = () => {
    const selectedKbs = knowledgeBases.filter(kb => selectedIds.includes(kb.id));
    console.log('💾 selectedKbs:', selectedKbs);
    return `已选择 ${selectedKbs.length} 个知识库`;
  };

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
        return <AppModelConfig skipModelVerification={isFromSecondPage} />
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
          await configStore.reloadFromStorage()

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

        // check embedding model
        if (
          !currentConfig.models.embedding.modelName &&
          !currentConfig.models.multiEmbedding?.modelName
        ) {
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

  return (
    <Layout
      connectionStatus={connectionStatus}
      lastChecked={lastChecked}
      isCheckingConnection={isCheckingConnection}
      onCheckConnection={checkModelEngineConnection}
      selectedKey={getEffectiveSelectedKey()}
      onBackToFirstPage={handleBackToFirstPage}
      onCompleteConfig={handleCompleteConfig}
      isSavingConfig={isSavingConfig}
      userRole={user?.role}
      showDebugButton={selectedKey === "3"}
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
        title={
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <ExclamationCircleFilled style={{ color: '#faad14', fontSize: 22 }} />
            <span style={{ fontWeight: 600, fontSize: 18, color: isDark ? '#fffbe6' : '#333' }}>{t('embedding.modal.title')}</span>
          </span>
        }
        open={embeddingModalOpen}
        onOk={async () => {
          setEmbeddingModalOpen(false);
          if (pendingJump) {
            setPendingJump(false);
            // get current config
            const currentConfig = configStore.getConfig();
            try {
              await configService.saveConfigToBackend(currentConfig);
            } catch (e) {
              message.error(t('setup.page.error.saveConfig'));
            }
            setSelectedKey("2");
          }
        }}
        onCancel={() => setEmbeddingModalOpen(false)}
        okText={t('embedding.modal.ok_continue')}
        cancelButtonProps={{ style: { display: 'none' } }}
        centered
        styles={{
          body: {
            padding: '32px 24px 24px 24px',
            background: isDark ? '#23272f' : '#fffbe6',
            borderRadius: 12,
            color: isDark ? '#eee' : '#333',
          }
        }}
        style={{
          borderRadius: 16,
          maxWidth: 1000,
          minWidth: 666,
          background: isDark ? '#23272f' : '#fff',
        }}
      >
        <div
          style={{
            fontSize: 16,
            color: isDark ? '#eee' : '#333',
            textAlign: 'center',
            marginBottom: 8,
          }}
          dangerouslySetInnerHTML={{
            __html: t('embedding.modal.content').replace(
              '<b>', `<b style=\"color:${isDark ? '#ffe58f' : '#faad14'}\">`
            ),
          }}
        />
        <div
          style={{
            textAlign: 'center',
            color: isDark ? '#aaa' : '#999',
            fontSize: 13,
            marginTop: 8,
          }}
        >
          {t('embedding.modal.tip')}
        </div>
      </Modal>
    </Layout>
  )
}
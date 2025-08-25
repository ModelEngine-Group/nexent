"use client"

import type React from "react"
import { useTranslation } from 'react-i18next' 
import { useState, useEffect, useRef, useLayoutEffect } from "react"

import { App } from 'antd'
import { InfoCircleFilled } from '@ant-design/icons'

// Import hooks and providers
import { useKnowledgeBaseContext, KnowledgeBaseProvider } from './contexts/KnowledgeBaseContext'
import { useDocumentContext, DocumentProvider } from './contexts/DocumentContext'
import { useUIContext, UIProvider } from './contexts/UIStateContext'
import { KnowledgeBase } from '@/types/knowledgeBase'
import knowledgeBaseService from '@/services/knowledgeBaseService'
import knowledgeBasePollingService from '@/services/knowledgeBasePollingService'
import { API_ENDPOINTS } from '@/services/api'
import { 
  SETUP_PAGE_CONTAINER, 
  FLEX_TWO_COLUMN_LAYOUT,
  STANDARD_CARD
} from '@/lib/layoutConstants'

// Import components
import KnowledgeBaseList from './components/knowledge/KnowledgeBaseList'
import DocumentList from './components/document/DocumentList'
import { useConfirmModal } from '@/components/ui/ConfirmModal'

// EmptyState component defined directly in this file
interface EmptyStateProps {
  icon?: React.ReactNode | string
  title: string
  description?: string
  action?: React.ReactNode
  containerHeight?: string
}

const EmptyState: React.FC<EmptyStateProps> = ({
  icon = '📋',
  title,
  description,
  action,
  containerHeight = '100%'
}) => {
  return (
    <div 
      className="flex items-center justify-center p-4"
      style={{ height: containerHeight }}
    >
      <div className="text-center">
        {typeof icon === 'string' ? (
          <div className="text-gray-400 text-3xl mb-2">{icon}</div>
        ) : (
          <div className="text-gray-400 mb-2">{icon}</div>
        )}
        <h3 className="text-base font-medium text-gray-700 mb-1">{title}</h3>
        {description && (
          <p className="text-gray-500 max-w-md text-xs mb-4">{description}</p>
        )}
        {action && (
          <div className="mt-2">{action}</div>
        )}
      </div>
    </div>
  )
}

// Combined AppProvider implementation
interface AppProviderProps {
  children: React.ReactNode
}

/**
 * AppProvider - 为应用提供全局状态管理
 * 
 * 将知识库、文档和UI状态管理组合在一起，方便一次引入所有上下文
 */
const AppProvider: React.FC<AppProviderProps> = ({ children }) => {
  return (
    <KnowledgeBaseProvider>
      <DocumentProvider>
        <UIProvider>
          {children}
        </UIProvider>
      </DocumentProvider>
    </KnowledgeBaseProvider>
  )
}

// Update the wrapper component
interface DataConfigWrapperProps {
  isActive?: boolean;
}

export default function DataConfigWrapper({ isActive = false }: DataConfigWrapperProps) {
  return (
    <AppProvider>
      <DataConfig isActive={isActive} />
    </AppProvider>
  )
}

interface DataConfigProps {
  isActive: boolean;
}

function DataConfig({ isActive }: DataConfigProps) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const { confirm } = useConfirmModal();

  // 组件初始化时清除缓存
  useEffect(() => {
    localStorage.removeItem('preloaded_kb_data');
    localStorage.removeItem('kb_cache');
  }, []);

  // Get context values
  const { 
    state: kbState,
    fetchKnowledgeBases,
    createKnowledgeBase,
    deleteKnowledgeBase,
    selectKnowledgeBase,
    setActiveKnowledgeBase,
    isKnowledgeBaseSelectable,
    refreshKnowledgeBaseData,
    loadUserSelectedKnowledgeBases,
    saveUserSelectedKnowledgeBases,
  } = useKnowledgeBaseContext();

  const {
    state: docState,
    fetchDocuments,
    uploadDocuments,
    deleteDocument,
    dispatch: docDispatch
  } = useDocumentContext();

  const {
    state: uiState,
    setDragging,
    dispatch: uiDispatch
  } = useUIContext();

  // Create mode state
  const [isCreatingMode, setIsCreatingMode] = useState(false);
  const [newKbName, setNewKbName] = useState("");
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [hasClickedUpload, setHasClickedUpload] = useState(false);

  // 添加监听选中新知识库的事件
  useEffect(() => {
    const handleSelectNewKnowledgeBase = (e: CustomEvent) => {
      const { knowledgeBase } = e.detail;
      if (knowledgeBase) {
        setIsCreatingMode(false);
        setHasClickedUpload(false);
        setActiveKnowledgeBase(knowledgeBase);
        fetchDocuments(knowledgeBase.id);
      }
    };
    
    window.addEventListener('selectNewKnowledgeBase', handleSelectNewKnowledgeBase as EventListener);
    
    return () => {
      window.removeEventListener('selectNewKnowledgeBase', handleSelectNewKnowledgeBase as EventListener);
    };
  }, [kbState.knowledgeBases, setActiveKnowledgeBase, fetchDocuments, setIsCreatingMode, setHasClickedUpload]);



  // 基于 isActive 状态的用户配置加载和保存逻辑
  const prevIsActiveRef = useRef<boolean | null>(null); // 初始化为 null 来区分首次渲染
  const hasLoadedRef = useRef(false); // 跟踪是否已经加载过配置
  const savedSelectedIdsRef = useRef<string[]>([]); // 保存当前选中的知识库ID
  const savedKnowledgeBasesRef = useRef<any[]>([]); // 保存当前知识库列表
  const hasUserInteractedRef = useRef(false); // 跟踪用户是否有过交互（防止初始加载时误保存空状态）

  // 监听 isActive 状态变化
  useLayoutEffect(() => {
    // 清除可能影响状态的缓存
    localStorage.removeItem('preloaded_kb_data');
    localStorage.removeItem('kb_cache');

    const prevIsActive = prevIsActiveRef.current;

    // 进入第二页时标记准备加载
    if ((prevIsActive === null || !prevIsActive) && isActive) {
      hasLoadedRef.current = false; // 重置加载状态
      hasUserInteractedRef.current = false; // 重置交互状态，防止误保存
    }

    // 离开第二页时保存用户配置
    if (prevIsActive === true && !isActive) {
      // 只有在用户有过交互后才保存，防止初始加载时误保存空状态
      if (hasUserInteractedRef.current) {
        const saveConfig = async () => {
          localStorage.removeItem('preloaded_kb_data');
          localStorage.removeItem('kb_cache');

          try {
            await saveUserSelectedKnowledgeBases();
          } catch (error) {
            console.error('保存用户配置失败:', error);
          }
        };

        saveConfig();
      }

      hasLoadedRef.current = false; // 重置加载状态
    }

    // 更新 ref
    prevIsActiveRef.current = isActive;
  }, [isActive]);

  // 实时保存当前状态到 ref，确保卸载时能访问到
  useEffect(() => {
    savedSelectedIdsRef.current = kbState.selectedIds;
    savedKnowledgeBasesRef.current = kbState.knowledgeBases;
  }, [kbState.selectedIds, kbState.knowledgeBases]);

    // 获取授权头的辅助函数
const getAuthHeaders = () => {
  const session = typeof window !== "undefined" ? localStorage.getItem("session") : null;
  const sessionObj = session ? JSON.parse(session) : null;
  return {
    'Content-Type': 'application/json',
    'User-Agent': 'AgentFrontEnd/1.0',
    ...(sessionObj?.access_token && { "Authorization": `Bearer ${sessionObj.access_token}` }),
  };
};


  // 组件卸载时的保存逻辑
  useEffect(() => {
    return () => {
      // 组件卸载时，如果之前是活跃状态且用户有过交互，则执行保存
      if (prevIsActiveRef.current === true && hasUserInteractedRef.current) {
        // 使用保存的状态而不是当前可能已清空的状态
        const selectedKbNames = savedKnowledgeBasesRef.current
          .filter(kb => savedSelectedIdsRef.current.includes(kb.id))
          .map(kb => kb.name);

        try {
          // 使用fetch with keepalive确保请求能在页面卸载时发送
          fetch(API_ENDPOINTS.tenantConfig.updateKnowledgeList, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              ...getAuthHeaders()
            },
            body: JSON.stringify(selectedKbNames),
            keepalive: true
          }).catch(error => {
            console.error('卸载时保存失败:', error);
          });
        } catch (error) {
          console.error('卸载时保存请求异常:', error);
        }
      }
    };
  }, []);

  // 单独监听知识库加载状态，当知识库加载完成且处于活跃状态时加载用户配置
  useEffect(() => {
    // 只有在第二页活跃、知识库已加载、且尚未加载用户配置时才执行
    if (isActive && kbState.knowledgeBases.length > 0 && !kbState.isLoading && !hasLoadedRef.current) {
      const loadConfig = async () => {
        try {
          await loadUserSelectedKnowledgeBases();
          hasLoadedRef.current = true;
        } catch (error) {
          console.error('加载用户配置失败:', error);
        }
      };

      loadConfig();
    }
  }, [isActive, kbState.knowledgeBases.length, kbState.isLoading]);

  // Generate unique knowledge base name
  const generateUniqueKbName = (existingKbs: KnowledgeBase[]): string => {
    const baseNamePrefix = t('knowledgeBase.name.new');
    const existingNames = new Set(existingKbs.map(kb => kb.name));
    
    // 如果基础名称未被使用，直接返回
    if (!existingNames.has(baseNamePrefix)) {
      return baseNamePrefix;
    }
    
    // 否则尝试添加数字后缀，直到找到未被使用的名称
    let counter = 1;
    while (existingNames.has(`${baseNamePrefix}${counter}`)) {
      counter++;
    }
    
    return `${baseNamePrefix}${counter}`;
  };

  // Handle knowledge base click logic, set current active knowledge base
  const handleKnowledgeBaseClick = (kb: KnowledgeBase, fromUserClick: boolean = true) => {
    // 只有当是用户点击时才重置创建模式
    if (fromUserClick) {
      hasUserInteractedRef.current = true; // 标记用户有交互
      setIsCreatingMode(false); // Reset creating mode
      setHasClickedUpload(false); // 重置上传按钮点击状态
    }

    // 无论是否切换知识库，都需要获取最新文档信息
    const isChangingKB = !kbState.activeKnowledgeBase || kb.id !== kbState.activeKnowledgeBase.id;

    // 如果是切换知识库，更新激活状态
    if (isChangingKB) {
      setActiveKnowledgeBase(kb);
    }

    // 设置活动知识库ID到轮询服务
    knowledgeBasePollingService.setActiveKnowledgeBase(kb.id);
    
    // 调用知识库切换处理函数
    handleKnowledgeBaseChange(kb);
  }

  // Handle knowledge base change event
  const handleKnowledgeBaseChange = async (kb: KnowledgeBase) => {
    try {
      // Set loading state before fetching documents
      docDispatch({ type: 'SET_LOADING_DOCUMENTS', payload: true });

      // 获取最新文档数据
      const documents = await knowledgeBaseService.getAllFiles(kb.id);

      // 触发文档更新事件
      knowledgeBasePollingService.triggerDocumentsUpdate(kb.id, documents);

      // 后台更新知识库统计信息，但不重复获取文档
      setTimeout(async () => {
        try {
          // 直接调用 fetchKnowledgeBases 更新知识库列表数据
          await fetchKnowledgeBases(false, true);
        } catch (error) {
          console.error("获取知识库最新数据失败:", error);
        }
      }, 100);
    } catch (error) {
      console.error("获取文档列表失败:", error);
      message.error(t('knowledgeBase.message.getDocumentsFailed'));
      docDispatch({ type: 'ERROR', payload: t('knowledgeBase.message.getDocumentsFailed') });
    }
  };

  // Add a drag and drop upload related handler function
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(true);
  }

  const handleDragLeave = () => {
    setDragging(false);
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);

    // 如果是创建模式或有活动知识库，则处理文件
    if (isCreatingMode || kbState.activeKnowledgeBase) {
      const files = Array.from(e.dataTransfer.files);
      if (files.length > 0) {
        setUploadFiles(files);
        handleFileUpload();
      }
    } else {
      message.warning(t('knowledgeBase.message.selectFirst'));
    }
  }

  // Handle knowledge base deletion
  const handleDelete = (id: string) => {
    hasUserInteractedRef.current = true; // 标记用户有交互
    confirm({
      title: t('knowledgeBase.modal.deleteConfirm.title'),
      content: t('knowledgeBase.modal.deleteConfirm.content'),
      okText: t('common.confirm'),
      cancelText: t('common.cancel'),
      danger: true,
      onConfirm: async () => {
        try {
          await deleteKnowledgeBase(id);
          
          // Clear preloaded data, force fetch latest data from server
          localStorage.removeItem('preloaded_kb_data');

          // Delay 1 second before refreshing knowledge base list to ensure backend processing is complete
          setTimeout(async () => {
            await fetchKnowledgeBases(false, false);
            message.success(t('knowledgeBase.message.deleteSuccess'));
          }, 1000);
        } catch (error) {
          message.error(t('knowledgeBase.message.deleteError'));
        }
      }
    });
  }

  // Handle knowledge base sync
  const handleSync = () => {
    // When manually syncing, force fetch latest data from server
    refreshKnowledgeBaseData(true)
      .then(() => {
        message.success(t('knowledgeBase.message.syncSuccess'));
      })
      .catch((error) => {
        message.error(t('knowledgeBase.message.syncError', { error: error.message || t('common.unknownError') }));
      });
  }

  // Handle new knowledge base creation
  const handleCreateNew = () => {
    hasUserInteractedRef.current = true; // 标记用户有交互
    // Generate default knowledge base name
    const defaultName = generateUniqueKbName(kbState.knowledgeBases);
    setNewKbName(defaultName);
    setIsCreatingMode(true);
    setHasClickedUpload(false); // 重置上传按钮点击状态
    setUploadFiles([]); // 重置上传文件数组，清空所有待上传文件
  };

  // Handle document deletion
  const handleDeleteDocument = (docId: string) => {
    const kbId = kbState.activeKnowledgeBase?.id;
    if (!kbId) return;

    confirm({
      title: t('document.modal.deleteConfirm.title'),
      content: t('document.modal.deleteConfirm.content'),
      okText: t('common.confirm'),
      cancelText: t('common.cancel'),
      danger: true,
      onConfirm: async () => {
        try {
          await deleteDocument(kbId, docId);
          message.success(t('document.message.deleteSuccess'));
        } catch (error) {
          message.error(t('document.message.deleteError'));
        }
      }
    });
  }

  // 处理文件上传 - 在创建模式下先创建知识库再上传，在普通模式下直接上传
  const handleFileUpload = async () => {
    if (!uploadFiles.length) {
      message.warning(t('document.message.noFiles'));
      return;
    }
    const filesToUpload = uploadFiles;

    if (isCreatingMode) {
      if (!newKbName || newKbName.trim() === "") {
        message.warning(t('knowledgeBase.message.nameRequired'));
        return;
      }

      setHasClickedUpload(true);
      
      try {
        const nameExistsResult = await knowledgeBaseService.checkKnowledgeBaseNameExists(newKbName.trim());

        if (nameExistsResult) {
          message.error(t('knowledgeBase.message.nameExists', { name: newKbName.trim() }));
          setHasClickedUpload(false);
          return;
        }

        const newKB = await createKnowledgeBase(
          newKbName.trim(),
          t('knowledgeBase.description.default'),
          "elasticsearch"
        );
        
        if (!newKB) {
          message.error(t('knowledgeBase.message.createError'));
          setHasClickedUpload(false);
          return;
        }

        setIsCreatingMode(false);
        setActiveKnowledgeBase(newKB);
        knowledgeBasePollingService.setActiveKnowledgeBase(newKB.id);
        setHasClickedUpload(false);

        await uploadDocuments(newKB.id, filesToUpload);
        setUploadFiles([]);
        
        knowledgeBasePollingService.handleNewKnowledgeBaseCreation(
          newKB.name,
          0,
          filesToUpload.length,
          (populatedKB) => {
            setActiveKnowledgeBase(populatedKB);
            knowledgeBasePollingService.triggerKnowledgeBaseListUpdate(true);
          }
        ).catch((pollingError) => {
          console.error("Knowledge base creation polling failed:", pollingError);
        });
        
      } catch (error) {
        console.error(t('knowledgeBase.error.createUpload'), error);
        message.error(t('knowledgeBase.message.createUploadError'));
        setHasClickedUpload(false);
      }
      return;
    }
    
    const kbId = kbState.activeKnowledgeBase?.id;
    if (!kbId) {
      message.warning(t('knowledgeBase.message.selectFirst'));
      return;
    }
    
    try {
      await uploadDocuments(kbId, filesToUpload);
      setUploadFiles([]);
      
      knowledgeBasePollingService.triggerKnowledgeBaseListUpdate(true);

      knowledgeBasePollingService.startDocumentStatusPolling(
        kbId,
        (documents) => {
          console.log(t('knowledgeBase.log.documentsPolled', { count: documents.length }));
          knowledgeBasePollingService.triggerDocumentsUpdate(kbId, documents);
          window.dispatchEvent(new CustomEvent('documentsUpdated', {
            detail: { kbId, documents }
          }));
        }
      );
      
    } catch (error) {
      console.error(t('document.error.upload'), error);
      message.error(t('document.message.uploadError'));
    }
  }

  // File selection handling
  const handleFileSelect = (files: File[]) => {
    if (files && files.length > 0) {
      setUploadFiles(files);
    }
  }

  // Get current viewing knowledge base documents
  const viewingDocuments = (() => {
    // 在创建模式下返回空数组，因为新知识库还没有文档
    if (isCreatingMode) {
      return [];
    }

    // 正常模式下，使用activeKnowledgeBase
    return kbState.activeKnowledgeBase
      ? docState.documentsMap[kbState.activeKnowledgeBase.id] || []
      : [];
  })();

  // Get current knowledge base name
  const viewingKbName = kbState.activeKnowledgeBase?.name || (isCreatingMode ? newKbName : "");

  // 只要有文档上传成功，立即自动切换创建模式为 false
  useEffect(() => {
    if (isCreatingMode && viewingDocuments.length > 0) {
      setIsCreatingMode(false);
    }
  }, [isCreatingMode, viewingDocuments.length]);

  // Handle knowledge base selection
  const handleSelectKnowledgeBase = (id: string) => {
    hasUserInteractedRef.current = true; // 标记用户有交互
    selectKnowledgeBase(id);
    
    // When selecting knowledge base also get latest data (low priority background operation)
    setTimeout(async () => {
      try {
        // 使用较低优先级刷新数据，因为这不是关键操作
        await refreshKnowledgeBaseData(true);
      } catch (error) {
        console.error("刷新知识库数据失败:", error);
        // Error doesn't affect user experience
      }
    }, 500); // Delay execution, lower priority
  }

  // 在组件初始化或活动知识库变化时更新轮询服务中的活动知识库ID
  useEffect(() => {
    if (kbState.activeKnowledgeBase) {
      knowledgeBasePollingService.setActiveKnowledgeBase(kbState.activeKnowledgeBase.id);
    } else if (isCreatingMode && newKbName) {
      knowledgeBasePollingService.setActiveKnowledgeBase(newKbName);
    } else {
      knowledgeBasePollingService.setActiveKnowledgeBase(null);
    }
  }, [kbState.activeKnowledgeBase, isCreatingMode, newKbName]);

  // 在组件卸载时清理轮询
  useEffect(() => {
    return () => {
      // 停止所有轮询
      knowledgeBasePollingService.stopAllPolling();
    };
  }, []);

  // 创建模式下，知识库名称变化时，重置"名称已存在"状态
  const handleNameChange = (name: string) => {
    setNewKbName(name);
  };

  return (
    <>
      <div 
        className="w-full mx-auto"
        style={{ 
          maxWidth: SETUP_PAGE_CONTAINER.MAX_WIDTH,
          padding: `0 ${SETUP_PAGE_CONTAINER.HORIZONTAL_PADDING}`
        }}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <div className="flex h-full" style={{ gap: FLEX_TWO_COLUMN_LAYOUT.GAP }}>
          {/* Left knowledge base list - occupies 1/3 space */}
          <div style={{ width: FLEX_TWO_COLUMN_LAYOUT.LEFT_WIDTH }}>
            <KnowledgeBaseList
            knowledgeBases={kbState.knowledgeBases}
            selectedIds={kbState.selectedIds}
            activeKnowledgeBase={kbState.activeKnowledgeBase}
            currentEmbeddingModel={kbState.currentEmbeddingModel}
            isLoading={kbState.isLoading}
            onSelect={handleSelectKnowledgeBase}
            onClick={handleKnowledgeBaseClick}
            onDelete={handleDelete}
            onSync={handleSync}
            onCreateNew={handleCreateNew}
            isSelectable={isKnowledgeBaseSelectable}
            getModelDisplayName={(modelId) => modelId}
            containerHeight={SETUP_PAGE_CONTAINER.MAIN_CONTENT_HEIGHT}
            onKnowledgeBaseChange={() => {}} // No need to trigger repeatedly here as it's already handled in handleKnowledgeBaseClick
          />
        </div>
          
          {/* Right content area - occupies 2/3 space, now unified with config.tsx style */}
          <div style={{ width: FLEX_TWO_COLUMN_LAYOUT.RIGHT_WIDTH }}>
            {isCreatingMode ? (
              <DocumentList
                documents={[]}
                onDelete={() => {}}
                isCreatingMode={true}
                knowledgeBaseName={newKbName}
                onNameChange={handleNameChange}
                containerHeight={SETUP_PAGE_CONTAINER.MAIN_CONTENT_HEIGHT}
                hasDocuments={hasClickedUpload || docState.isUploading}
                // Upload related props
                isDragging={uiState.isDragging}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                onFileSelect={handleFileSelect}
                onUpload={() => handleFileUpload()}
                isUploading={docState.isUploading}
              />
            ) : kbState.activeKnowledgeBase ? (
              <DocumentList
                documents={viewingDocuments}
                onDelete={handleDeleteDocument}
                knowledgeBaseName={viewingKbName}
                modelMismatch={!isKnowledgeBaseSelectable(kbState.activeKnowledgeBase)}
                currentModel={kbState.currentEmbeddingModel || ''}
                knowledgeBaseModel={kbState.activeKnowledgeBase.embeddingModel}
                embeddingModelInfo={
                  !isKnowledgeBaseSelectable(kbState.activeKnowledgeBase) ?
                  `当前模型${kbState.currentEmbeddingModel || ''}与知识库模型${kbState.activeKnowledgeBase.embeddingModel}不匹配，无法使用` :
                  undefined
                }
                containerHeight={SETUP_PAGE_CONTAINER.MAIN_CONTENT_HEIGHT}
                hasDocuments={viewingDocuments.length > 0}
                // Upload related props
                isDragging={uiState.isDragging}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                onFileSelect={handleFileSelect}
                onUpload={() => handleFileUpload()}
                isUploading={docState.isUploading}
              />
            ) : (
              <div className={STANDARD_CARD.BASE_CLASSES} style={{ 
                height: SETUP_PAGE_CONTAINER.MAIN_CONTENT_HEIGHT,
                padding: STANDARD_CARD.PADDING,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center'
              }}>
                <EmptyState
                  title={t('knowledgeBase.empty.title')}
                  description={t('knowledgeBase.empty.description')}
                  icon={<InfoCircleFilled style={{ fontSize: 36, color: '#1677ff' }} />}
                  containerHeight="100%"
                />
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  )
}


import React, { useState, forwardRef, useImperativeHandle, useEffect, useCallback, useRef } from 'react';
import { message } from 'antd';
import type { UploadFile, UploadProps, RcFile } from 'antd/es/upload/interface';
import { useTranslation } from 'react-i18next';
import { API_ENDPOINTS } from '@/services/api';
import knowledgeBasePollingService from '@/services/knowledgeBasePollingService';
import UploadAreaUI from './UploadAreaUI';
import { 
  checkKnowledgeBaseNameExists,
  fetchKnowledgeBaseInfo,
  validateFileType,
} from './UploadService';

interface UploadAreaProps {
  isDragging?: boolean;
  onDragOver?: (e: React.DragEvent) => void;
  onDragLeave?: (e: React.DragEvent) => void;
  onDrop?: (e: React.DragEvent) => void;
  onFileSelect: (files: File[]) => void;
  selectedFiles?: File[];
  onUpload?: () => void;
  isUploading?: boolean;
  disabled?: boolean;
  componentHeight?: string;
  isCreatingMode?: boolean;
  uploadUrl?: string;
  indexName?: string;
  newKnowledgeBaseName?: string;
  modelMismatch?: boolean;
}

export interface UploadAreaRef {
  fileList: UploadFile[];
}

const UploadArea = forwardRef<UploadAreaRef, UploadAreaProps>(({
  onFileSelect,
  onUpload,
  isUploading = false,
  disabled = false,
  componentHeight = '300px',
  isCreatingMode = false,
  uploadUrl = '/api/upload',
  indexName = '',
  newKnowledgeBaseName = '',
  selectedFiles = [],
  modelMismatch = false
}, ref) => {
  const { t } = useTranslation('common');
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [nameExists, setNameExists] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isKnowledgeBaseReady, setIsKnowledgeBaseReady] = useState(false);
  const currentKnowledgeBaseRef = useRef<string>('');
  const pendingRequestRef = useRef<AbortController | null>(null);
  const prevFileListRef = useRef<UploadFile[]>([]);
  
  useEffect(() => {
    prevFileListRef.current = fileList;
  }, [fileList]);
  
  // 重置所有状态的函数
  const resetAllStates = useCallback(() => {
    setFileList([]);
    setNameExists(false);
    setIsLoading(true);
    setIsKnowledgeBaseReady(false);
  }, []);

  // 监听知识库变化，重置文件列表并获取知识库信息
  useEffect(() => {
    // 如果知识库名称没有变化，不进行重置
    if (indexName === currentKnowledgeBaseRef.current) {
      return;
    }

    // 取消之前的请求
    if (pendingRequestRef.current) {
      pendingRequestRef.current.abort();
      pendingRequestRef.current = null;
    }

    // 立即重置状态和清空文件列表
    resetAllStates();
    
    // 更新当前知识库引用
    currentKnowledgeBaseRef.current = indexName;

    if (!indexName || isCreatingMode) {
      setIsKnowledgeBaseReady(true);
      setIsLoading(false);
      return;
    }

    // 创建新的 AbortController
    const abortController = new AbortController();
    pendingRequestRef.current = abortController;

    // 使用服务函数获取知识库信息
    fetchKnowledgeBaseInfo(
      indexName, 
      abortController, 
      currentKnowledgeBaseRef,
      () => {
        setIsKnowledgeBaseReady(true);
        setIsLoading(false);
      },
      () => {
        setIsKnowledgeBaseReady(false);
        setIsLoading(false);
      },
      t
    );

    // 清理函数
    return () => {
      if (pendingRequestRef.current) {
        pendingRequestRef.current.abort();
        pendingRequestRef.current = null;
      }
    };
  }, [indexName, isCreatingMode, resetAllStates, t]);
  
  // 暴露文件列表给父组件
  useImperativeHandle(ref, () => ({
    fileList
  }), [fileList]);
  
  // 检查知识库名称是否已存在
  useEffect(() => {
    if (!isCreatingMode || !newKnowledgeBaseName) {
      setNameExists(false);
      return;
    }

    let isActive = true;

    const checkName = async () => {
      try {
        const exists = await checkKnowledgeBaseNameExists(newKnowledgeBaseName, t);
        if (isActive) {
          setNameExists(exists);
        }
      } catch (error) {
        if (isActive) {
          console.error(t('knowledgeBase.error.checkName'), error);
        }
      }
    };
      
    checkName();

    return () => {
      isActive = false;
    };
  }, [isCreatingMode, newKnowledgeBaseName, t]);
  
  // 处理文件变更
  const handleChange = useCallback(({ fileList: newFileList }: { fileList: UploadFile[] }) => {

    // 确保只更新当前知识库的文件列表
    if (isCreatingMode || indexName === currentKnowledgeBaseRef.current) {
      setFileList(newFileList);
    } else {
      return;
    }
    
    // 检查上传是否刚刚完成
    const prevFileList = prevFileListRef.current;
    const uploadWasInProgress = prevFileList.some(f => f.status === 'uploading');
    const uploadIsNowFinished = newFileList.length > 0 && !newFileList.some(f => f.status === 'uploading');


    if (uploadWasInProgress && uploadIsNowFinished) {
      console.log('[UploadArea] Upload completed, calling onUpload callback');
      // 上传完成后仅调用外部的上传完成回调，由 KnowledgeBaseManager 统一管理轮询
      if (onUpload) {
        onUpload();
      }
    }
    
    // 触发文件选择回调, 传递所有文件
    const files = newFileList
      .map(file => file.originFileObj)
      .filter((file): file is File => !!file);

    if (files.length > 0) {
      onFileSelect(files);
    }
  }, [indexName, onFileSelect, isCreatingMode, newKnowledgeBaseName, onUpload]);

  // 处理自定义上传请求
  const handleCustomRequest = useCallback((options: any) => {
    
    // 实际上传由父组件的 handleFileUpload 处理
    const { onSuccess, file } = options;
    setTimeout(() => {
      onSuccess({}, file);
    }, 100);
  }, []);

  // 上传组件属性
  const uploadProps: UploadProps = {
    name: 'file',
    multiple: true,
    fileList,
    onChange: handleChange,
    customRequest: handleCustomRequest,
    accept: '.pdf,.docx,.pptx,.xlsx,.md,.txt,.csv',
    showUploadList: true,
    disabled: disabled,
    progress: {
      strokeColor: {
        '0%': '#108ee9',
        '100%': '#87d068',
      },
      size: 3,
      format: (percent?: number) => percent ? `${parseFloat(percent.toFixed(2))}%` : '0%'
    },
    beforeUpload: (file) => validateFileType(file, t)
  };
  
  return (
    <UploadAreaUI
      fileList={fileList}
      uploadProps={uploadProps}
      isLoading={isLoading}
      isKnowledgeBaseReady={isKnowledgeBaseReady}
      isCreatingMode={isCreatingMode}
      nameExists={nameExists}
      isUploading={isUploading}
      disabled={disabled}
      componentHeight={componentHeight}
      newKnowledgeBaseName={newKnowledgeBaseName}
      selectedFiles={selectedFiles}
      modelMismatch={modelMismatch}
    />
  );
});

export default UploadArea; 
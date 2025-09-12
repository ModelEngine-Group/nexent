import React, { useState, forwardRef, useImperativeHandle, useEffect, useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';

import type { UploadFile, UploadProps, RcFile } from 'antd/es/upload/interface';
import { App } from 'antd';

import { NAME_CHECK_STATUS } from '@/const/agentConfig';
import log from "@/lib/logger";
import { 
  checkKnowledgeBaseName,
  fetchKnowledgeBaseInfo,
  validateFileType,
} from '@/services/uploadService';

import UploadAreaUI from './UploadAreaUI';

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
  indexName = '',
  newKnowledgeBaseName = '',
  selectedFiles = [],
  modelMismatch = false
}, ref) => {
  const { t } = useTranslation('common');
  const { message } = App.useApp();
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [nameStatus, setNameStatus] = useState<string>('available');
  const [isLoading, setIsLoading] = useState(false);
  const [isKnowledgeBaseReady, setIsKnowledgeBaseReady] = useState(false);
  const currentKnowledgeBaseRef = useRef<string>('');
  const pendingRequestRef = useRef<AbortController | null>(null);
  const prevFileListRef = useRef<UploadFile[]>([]);
  
  useEffect(() => {
    prevFileListRef.current = fileList;
  }, [fileList]);
  
  // Function to reset all states
  const resetAllStates = useCallback(() => {
    setFileList([]);
    setNameStatus('available');
    setIsLoading(true);
    setIsKnowledgeBaseReady(false);
  }, []);

  // Listen for knowledge base changes, reset file list and get knowledge base info
  useEffect(() => {
    // If knowledge base name hasn't changed, don't reset
    if (indexName === currentKnowledgeBaseRef.current) {
      return;
    }

    // Cancel previous request
    if (pendingRequestRef.current) {
      pendingRequestRef.current.abort();
      pendingRequestRef.current = null;
    }

    // Immediately reset state and clear file list
    resetAllStates();
    
    // Update current knowledge base reference
    currentKnowledgeBaseRef.current = indexName;

    if (!indexName || isCreatingMode) {
      setIsKnowledgeBaseReady(true);
      setIsLoading(false);
      return;
    }

    // Create new AbortController
    const abortController = new AbortController();
    pendingRequestRef.current = abortController;

    // Use service function to get knowledge base info
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
      t,
      message
    );

    // Cleanup function
    return () => {
      if (pendingRequestRef.current) {
        pendingRequestRef.current.abort();
        pendingRequestRef.current = null;
      }
    };
  }, [indexName, isCreatingMode, resetAllStates, t, message]);
  
  // Expose file list to parent component
  useImperativeHandle(ref, () => ({
    fileList
  }), [fileList]);
  
  // Check if knowledge base name already exists
  useEffect(() => {
    if (!isCreatingMode || !newKnowledgeBaseName) {
      setNameStatus('available');
      return;
    }

    const checkName = async () => {
      try {
        const result = await checkKnowledgeBaseName(newKnowledgeBaseName, t);
        setNameStatus(result.status);
      } catch (error) {
        log.error(t('knowledgeBase.error.checkName'), error);
        setNameStatus(NAME_CHECK_STATUS.CHECK_FAILED); // Handle check failure
      }
    };
      
    const timer = setTimeout(() => {
        checkName();
    }, 300); // Debounce for 300ms

    return () => {
        clearTimeout(timer);
    };
  }, [isCreatingMode, newKnowledgeBaseName, t]);
  
  // Handle file changes
  const handleChange = useCallback(({ fileList: newFileList }: { fileList: UploadFile[] }) => {

    // Ensure only updating current knowledge base's file list
    if (isCreatingMode || indexName === currentKnowledgeBaseRef.current) {
      setFileList(newFileList);
    } else {
      return;
    }
    
    // Check if upload just completed
    const prevFileList = prevFileListRef.current;
    const uploadWasInProgress = prevFileList.some(f => f.status === 'uploading');
    const uploadIsNowFinished = newFileList.length > 0 && !newFileList.some(f => f.status === 'uploading');


    if (uploadWasInProgress && uploadIsNowFinished) {
      // After upload completion only call external upload completion callback, let KnowledgeBaseManager manage polling uniformly
      if (onUpload) {
        onUpload();
      }
    }
    
    // Trigger file selection callback, pass all files
    const files = newFileList
      .map(file => file.originFileObj)
      .filter((file): file is RcFile => !!file);

    if (files.length > 0) {
      onFileSelect(files as unknown as File[]);
    }
  }, [indexName, onFileSelect, isCreatingMode, newKnowledgeBaseName, onUpload]);

  // Handle custom upload request
  const handleCustomRequest = useCallback((options: any) => {
    
    // Actual upload is handled by parent component's handleFileUpload
    const { onSuccess, file } = options;
    setTimeout(() => {
      onSuccess({}, file);
    }, 100);
  }, []);

  // Upload component properties
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
    beforeUpload: (file) => validateFileType(file, t, message)
  };
  
  return (
    <UploadAreaUI
      fileList={fileList}
      uploadProps={uploadProps}
      isLoading={isLoading}
      isKnowledgeBaseReady={isKnowledgeBaseReady}
      isCreatingMode={isCreatingMode}
      nameStatus={nameStatus}
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
import React from "react";
import { useTranslation } from "react-i18next";

import { NAME_CHECK_STATUS } from "@/const/agentConfig";
import { Upload, Progress } from "antd";
import { WarningFilled } from "@ant-design/icons";
import { Inbox } from "lucide-react";
import type { UploadFile, UploadProps } from "antd/es/upload/interface";

const { Dragger } = Upload;

interface UploadAreaUIProps {
  fileList: UploadFile[];
  uploadProps: UploadProps;
  isLoading: boolean;
  isKnowledgeBaseReady: boolean;
  isCreatingMode: boolean;
  nameStatus: string;
  isUploading: boolean;
  disabled: boolean;
  disabledMessage?: string;
  componentHeight: string;
  newKnowledgeBaseName: string;
  selectedFiles: File[];
  modelMismatch?: boolean;
}

const UploadAreaUI: React.FC<UploadAreaUIProps> = ({
  fileList,
  uploadProps,
  isLoading,
  isKnowledgeBaseReady,
  isCreatingMode,
  nameStatus,
  isUploading,
  disabled,
  disabledMessage,
  componentHeight,
  newKnowledgeBaseName,
  modelMismatch = false,
}) => {
  const { t } = useTranslation("common");
  const resolvedComponentHeight = isCreatingMode ? "146px" : componentHeight;
  const componentHeightStyle = {
    height: resolvedComponentHeight,
    minHeight: resolvedComponentHeight,
  };

  // Loading state UI
  if (isLoading) {
    return (
      <div
        className={`${
          isCreatingMode
            ? "border-0 bg-transparent px-0 pb-0 pt-0"
            : "border-0 bg-transparent p-0"
        } ${isCreatingMode ? "h-[146px] min-h-[146px]" : "min-h-[150px]"}`}
        style={componentHeightStyle}
      >
        <div className="flex justify-center items-center h-full">
          <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500 mx-auto mb-2"></div>
          <p className="text-sm text-blue-600 font-medium ml-2">
            {t("common.loading")}
          </p>
        </div>
        {isCreatingMode && isUploading && (
          <div className="mt-2 text-center">
            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500 mx-auto mb-2"></div>
            <p className="text-sm text-blue-600 font-medium">
              {t("knowledgeBase.status.uploadingAndCreating")}
            </p>
          </div>
        )}
      </div>
    );
  }

  // Knowledge base not ready UI
  if (!isKnowledgeBaseReady && !isCreatingMode) {
    return (
      <div
        className="min-h-[150px] border-0 bg-transparent p-0"
        style={componentHeightStyle}
      >
        <div className="h-full border-2 border-dashed border-gray-200 rounded-md flex flex-col items-center justify-center bg-white">
          <WarningFilled className="text-[32px] text-yellow-500 mb-4" />
          <p className="text-gray-600 text-base mb-2">
            {t("knowledgeBase.status.notReady")}
          </p>
          <p className="text-gray-400 text-sm">{t("common.retryLater")}</p>
        </div>
      </div>
    );
  }

  // Disabled state UI
  if (disabled) {
    return (
      <div
        className="min-h-[150px] border-0 bg-transparent p-0 opacity-50 cursor-not-allowed"
        style={componentHeightStyle}
      >
        <div className="border-2 border-dashed border-gray-300 bg-white rounded-md p-4 text-center flex flex-col items-center justify-center h-full">
          <div className="mb-0.5 text-blue-500 text-lg">📄</div>
          <p className="mb-0.5 text-gray-700 text-xs font-medium">
            {disabledMessage || t("knowledgeBase.hint.selectFirst")}
          </p>
        </div>
      </div>
    );
  }

  // Name already exists UI - render different messages based on status
  if (
    isCreatingMode &&
    (nameStatus === NAME_CHECK_STATUS.EXISTS_IN_TENANT ||
      nameStatus === NAME_CHECK_STATUS.EXISTS_IN_OTHER_TENANT)
  ) {
    const messageKey =
      nameStatus === NAME_CHECK_STATUS.EXISTS_IN_TENANT
        ? "knowledgeBase.message.nameExists"
        : "knowledgeBase.error.nameExistsInOtherTenant";

    return (
      <div
        className={
          isCreatingMode
            ? "border-0 bg-transparent h-[146px] min-h-[146px] px-0 pb-0 pt-0"
            : "border-0 bg-transparent min-h-[150px] p-0"
        }
        style={componentHeightStyle}
      >
        <div className="flex h-full flex-col items-center justify-center rounded-2xl border-2 border-dashed border-red-200 bg-red-50/30 p-4 text-center">
          <div className="mb-4 text-red-500 text-lg">
            <WarningFilled style={{ fontSize: 36, color: "#ff4d4f" }} />
          </div>
          <p className="mb-2 text-red-600 text-lg font-medium">
            {t(messageKey, { name: newKnowledgeBaseName })}
          </p>
          <p className="text-gray-500 text-sm max-w-md">
            {t("knowledgeBase.hint.changeName")}
          </p>
        </div>
      </div>
    );
  }

  // Model mismatch status UI
  if (modelMismatch) {
    return (
      <div
        className="flex min-h-[150px] items-center justify-center border-0 bg-transparent p-0"
        style={componentHeightStyle}
      >
        <span className="text-base font-medium text-center leading-[1.7] text-gray-500">
          {t("knowledgeBase.upload.modelMismatch.description")}
        </span>
      </div>
    );
  }

  // Default UI state
  return (
    <div
      className={`${
        isCreatingMode
          ? "border-0 bg-transparent px-0 pb-0 pt-0"
          : "border-0 bg-transparent p-0"
      } ${isCreatingMode ? "h-[146px] min-h-[146px]" : "min-h-[150px]"}`}
      style={componentHeightStyle}
    >
      <div className="h-full flex transition-all duration-300 ease-in-out">
        {/* Upload area container */}
        <div
          className={`transition-all duration-300 ease-in-out ${
            !isLoading && fileList.length > 0 ? "w-[40%] pr-2" : "w-full"
          }`}
        >
          <div className="relative h-full">
            {/* Upload area layer */}
            <div
              className="absolute inset-0 transition-opacity duration-300 ease-in-out"
              onDragOver={(e) => {
                e.preventDefault();
                e.stopPropagation();
              }}
              onDragEnter={(e) => {
                e.preventDefault();
                e.stopPropagation();
              }}
              onDragLeave={(e) => {
                e.preventDefault();
                e.stopPropagation();
              }}
              onDrop={(e) => {
                e.preventDefault();
                e.stopPropagation();
              }}
            >
              <div className="h-full">
                <Dragger
                  {...uploadProps}
                  className={`!h-full flex flex-col justify-center !rounded-2xl !border-2 !border-dashed ${
                    isCreatingMode
                      ? "!border-blue-300 !bg-white shadow-sm"
                      : "!border-blue-200 !bg-blue-50/30"
                  }`}
                  showUploadList={false}
                  style={{
                    height: "100%",
                    overflow: isCreatingMode ? "hidden" : "auto",
                  }}
                >
                  <div className="flex flex-col items-center justify-center">
                    <p
                      className={`ant-upload-drag-icon ${
                        isCreatingMode ? "!mb-2" : "!mb-4"
                      }`}
                    >
                      <Inbox
                        size={isCreatingMode ? 32 : 48}
                        className="text-blue-600"
                      />
                    </p>
                    <p
                      className={`ant-upload-text ${
                        isCreatingMode ? "!mb-1 text-sm" : "!mb-2 text-base"
                      }`}
                    >
                      {t("knowledgeBase.upload.dragHint")}
                    </p>
                    <p
                      className={`ant-upload-hint text-gray-500 ${
                        isCreatingMode ? "text-xs" : ""
                      }`}
                    >
                      {t("knowledgeBase.upload.supportedFormats")}
                    </p>
                    <p
                      className={`ant-upload-hint text-gray-500 ${
                        isCreatingMode ? "!mt-0 text-xs" : "!mt-1"
                      }`}
                    >
                      {t("knowledgeBase.upload.fileSizeLimit")}
                    </p>
                  </div>
                </Dragger>
              </div>
            </div>
          </div>
        </div>

        {/* File list area */}
        <div
          className={`rounded-lg transition-all duration-300 ease-in-out overflow-hidden ${
            !isLoading && fileList.length > 0
              ? "w-[60%] opacity-100 pl-2"
              : "w-0 opacity-0"
          }`}
        >
          {fileList.length > 0 && !isLoading && (
            <div className="h-full">
              <div className="h-full border border-gray-200 rounded-lg">
                <div className="flex items-center justify-between p-3 border-b border-gray-100 bg-gray-50">
                  <h4 className="text-sm font-medium text-gray-700 m-0">
                    {t("knowledgeBase.upload.completed")}
                  </h4>
                  <span className="text-xs text-gray-500">
                    {t("knowledgeBase.upload.fileCount", {
                      count: fileList.length,
                    })}
                  </span>
                </div>
                <div className="overflow-auto h-[calc(100%_-_41px)]">
                  {fileList.map((file) => (
                    <div
                      key={file.uid}
                      className="border-b border-gray-100 last:border-b-0"
                    >
                      <div className="flex items-center justify-between py-2 px-3 hover:bg-gray-50 transition-colors">
                        <div className="flex items-center flex-1 min-w-0">
                          <div className="flex-1 min-w-0">
                            <div className="text-xs font-medium text-gray-700 truncate">
                              {file.name}
                            </div>
                            {file.status === "uploading" && (
                              <div className="mt-1">
                                <Progress
                                  percent={file.percent}
                                  size="small"
                                  showInfo={false}
                                  strokeColor={{
                                    "0%": "#108ee9",
                                    "100%": "#87d068",
                                  }}
                                />
                              </div>
                            )}
                          </div>
                        </div>
                        <div className="ml-3 flex items-center text-xs">
                          {file.status === "uploading" && (
                            <span className="text-blue-500">
                              {t("knowledgeBase.upload.status.uploading")}
                            </span>
                          )}
                          {file.status === "done" && (
                            <span className="text-green-500">
                              {t("knowledgeBase.upload.status.completed")}
                            </span>
                          )}
                          {file.status === "error" && (
                            <span className="text-red-500">
                              {t("knowledgeBase.upload.status.failed")}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {isCreatingMode && isUploading && (
        <div className="mt-2 text-center">
          <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500 mx-auto mb-2"></div>
          <p className="text-sm text-blue-600 font-medium">
            {t("knowledgeBase.status.uploadingAndCreating")}
          </p>
        </div>
      )}
    </div>
  );
};

export default UploadAreaUI;

import React from 'react'
import { Button, Checkbox, ConfigProvider } from 'antd'
import { SyncOutlined, PlusOutlined } from '@ant-design/icons'
import { KnowledgeBase } from '@/types/knowledgeBase'
import { useTranslation } from 'react-i18next'

// Knowledge base layout constants configuration
const KB_LAYOUT = {
  // Knowledge base row height configuration
  ROW_PADDING: 'py-4', // Row vertical padding
  HEADER_PADDING: 'p-3', // List header padding
  BUTTON_PADDING: 'p-2', // Create button area padding
  TAG_SPACING: 'gap-0.5', // Spacing between tags
  TAG_MARGIN: 'mt-2.5', // Tag container top margin
  // Tag related configuration
  TAG_PADDING: 'px-1.5 py-0.5', // Tag padding
  TAG_TEXT: 'text-xs font-medium', // Tag text style
  TAG_ROUNDED: 'rounded-md', // Tag border radius
  // Line break related configuration
  TAG_BREAK_HEIGHT: 'h-0.5', // Line break interval height
  SECOND_ROW_TAG_MARGIN: 'mt-0.5', // Second row tag top margin
  // Other layout configuration
  TITLE_MARGIN: 'ml-2', // Title left margin
  EMPTY_STATE_PADDING: 'py-4', // Empty state padding
  // Title related configuration
  TITLE_TEXT: 'text-xl font-bold', // Title text style
  KB_NAME_TEXT: 'text-lg font-medium', // Knowledge base name text style
  // Knowledge base name configuration
  KB_NAME_MAX_WIDTH: '220px', // Knowledge base name maximum width
  KB_NAME_OVERFLOW: {        // Knowledge base name overflow style
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    display: 'block'
  }
}

interface KnowledgeBaseListProps {
  knowledgeBases: KnowledgeBase[]
  selectedIds: string[]
  activeKnowledgeBase: KnowledgeBase | null
  currentEmbeddingModel: string | null
  isLoading?: boolean
  onSelect: (id: string) => void
  onClick: (kb: KnowledgeBase) => void
  onDelete: (id: string) => void
  onSync: () => void
  onCreateNew: () => void
  isSelectable: (kb: KnowledgeBase) => boolean
  getModelDisplayName: (modelId: string) => string
  containerHeight?: string // Container total height, consistent with DocumentList
  onKnowledgeBaseChange?: () => void // New: Callback function when knowledge base changes
}

const KnowledgeBaseList: React.FC<KnowledgeBaseListProps> = ({
  knowledgeBases,
  selectedIds,
  activeKnowledgeBase,
  currentEmbeddingModel,
  isLoading = false,
  onSelect,
  onClick,
  onDelete,
  onSync,
  onCreateNew,
  isSelectable,
  getModelDisplayName,
  containerHeight = '70vh', // Default container height consistent with DocumentList
  onKnowledgeBaseChange // New: Callback function when knowledge base changes
}) => {
  const { t } = useTranslation();

  // Format date function, keep only the date part
  const formatDate = (dateString: number) => {
    try {
      const date = new Date(dateString);
      return date.toISOString().split('T')[0]; // Only return YYYY-MM-DD part
    } catch (e) {
      return dateString; // If parsing fails, return original string
    }
  };


  return (
    <div className="w-full bg-white border border-gray-200 rounded-md flex flex-col" style={{ height: containerHeight }}>
      {/* Fixed header area */}
      <div className={`${KB_LAYOUT.HEADER_PADDING} border-b border-gray-200 shrink-0`}>
        <div className="flex items-center justify-between">
          <div>
            <h3 className={`${KB_LAYOUT.TITLE_MARGIN} ${KB_LAYOUT.TITLE_TEXT} text-gray-800`}>
              {t('knowledgeBase.list.title')}
            </h3>
          </div>
          <div className="flex items-center" style={{ gap: '6px' }}>
            <Button
              style={{
                padding: "4px 15px",
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "8px",
                backgroundColor: "#1677ff",
                color: "white",
                border: "none"
              }}
              className="hover:!bg-blue-600"
              type="primary"
              onClick={onCreateNew}
              icon={<PlusOutlined />}
            >
              {t('knowledgeBase.button.create')}
            </Button>
            <Button
              style={{
                padding: "4px 15px",
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "8px",
                backgroundColor: "#1677ff",
                color: "white",
                border: "none"
              }}
              className="hover:!bg-blue-600"
              type="primary"
              onClick={onSync}
            >
              <span style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                width: "14px",
                height: "14px"
              }}>
                <SyncOutlined spin={isLoading} style={{ color: "white" }} />
              </span>
              <span>{t('knowledgeBase.button.sync')}</span>
            </Button>
          </div>
        </div>
      </div>

      {/* Fixed selection status area */}
      <div className="border-b border-gray-200 shrink-0 relative z-10 shadow-md">
        <div className="px-5 py-2 bg-blue-50">
          <div className="flex items-center">
            <span className="font-medium text-blue-700">{t('knowledgeBase.selected.prefix')} </span>
            <span className="mx-1 text-blue-600 font-bold text-lg">{selectedIds.length}</span>
            <span className="font-medium text-blue-700">{t('knowledgeBase.selected.suffix')}</span>
          </div>

          {selectedIds.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-2 mb-1">
              {selectedIds.map((id) => {
                const kb = knowledgeBases.find((kb) => kb.id === id)
                return kb ? (
                  <span
                    key={id}
                    className="inline-flex items-center px-2 py-0.5 bg-blue-100 text-blue-800 rounded-md text-sm font-medium group"
                    style={{ maxWidth: 'fit-content' }}
                  >
                    <span
                      className="truncate"
                      style={{
                        maxWidth: '150px',
                        ...KB_LAYOUT.KB_NAME_OVERFLOW
                      }}
                      title={kb.name}
                    >
                      {kb.name}
                    </span>
                    <button
                      className="ml-1.5 text-blue-600 hover:text-blue-800 flex-shrink-0"
                      onClick={() => onSelect(id)}
                      aria-label={t('knowledgeBase.button.removeKb', { name: kb.name })}
                    >
                      ×
                    </button>
                  </span>
                ) : null
              })}
            </div>
          )}
        </div>
      </div>

      {/* Scrollable knowledge base list area */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden">
        {knowledgeBases.length > 0 ? (
          <div className="divide-y-0">
            {knowledgeBases.map((kb, index) => {
              const canSelect = isSelectable(kb)
              const isSelected = selectedIds.includes(kb.id)
              const isActive = activeKnowledgeBase?.id === kb.id
              const isMismatchedAndSelected = isSelected && !canSelect

              return (
                <div
                  key={kb.id}
                  className={`${KB_LAYOUT.ROW_PADDING} px-2 hover:bg-gray-50 cursor-pointer transition-colors ${index > 0 ? "border-t border-gray-200" : ""}`}
                  style={{
                    borderLeftWidth: '4px',
                    borderLeftStyle: 'solid',
                    borderLeftColor: isActive ? '#3b82f6' : 'transparent',
                    backgroundColor: isActive ? 'rgb(226, 240, 253)' : 'inherit'
                  }}
                  onClick={() => {
                    onClick(kb);
                    if (onKnowledgeBaseChange) onKnowledgeBaseChange();
                  }}
                >
                  <div className="flex items-start">
                    <div className="flex-shrink-0">
                      <div className="px-2" onClick={(e) => {
                        e.stopPropagation();
                        if (canSelect || isSelected) {
                          onSelect(kb.id);
                        }
                      }}
                        style={{
                          minWidth: '40px',
                          minHeight: '40px',
                          display: 'flex',
                          alignItems: 'flex-start',
                          justifyContent: 'center'
                        }}>
                        <ConfigProvider
                          theme={{
                            token: {
                              // If selected with model mismatch, use light blue, otherwise default blue
                              colorPrimary: isMismatchedAndSelected ? '#90caf9' : '#1677ff',
                            },
                          }}
                        >
                          <Checkbox
                            checked={isSelected}
                            onChange={(e) => {
                              e.stopPropagation()
                              onSelect(kb.id)
                            }}
                            disabled={!canSelect && !isSelected}
                            style={{
                              cursor: (canSelect || isSelected) ? 'pointer' : 'not-allowed',
                              transform: 'scale(1.5)',
                            }}
                          />
                        </ConfigProvider>
                      </div>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between">
                        <p
                          className="text-base font-medium text-gray-800 truncate"
                          style={{
                            maxWidth: KB_LAYOUT.KB_NAME_MAX_WIDTH,
                            ...KB_LAYOUT.KB_NAME_OVERFLOW
                          }}
                          title={kb.name}
                        >
                          {kb.name}
                        </p>
                        <button
                          className="text-red-500 hover:text-red-700 text-xs font-medium ml-2"
                          onClick={(e) => {
                            e.stopPropagation()
                            onDelete(kb.id)
                          }}
                        >
                          {t('common.delete')}
                        </button>
                      </div>
                      <div className={`flex flex-wrap items-center ${KB_LAYOUT.TAG_MARGIN} ${KB_LAYOUT.TAG_SPACING}`}>
                        {/* Document count tag */}
                        <span className={`inline-flex items-center ${KB_LAYOUT.TAG_PADDING} ${KB_LAYOUT.TAG_ROUNDED} ${KB_LAYOUT.TAG_TEXT} bg-gray-200 text-gray-800 border border-gray-200 mr-1`}>
                          {t('knowledgeBase.tag.documents', { count: kb.documentCount || 0 })}
                        </span>

                        {/* Chunk count tag */}
                        <span className={`inline-flex items-center ${KB_LAYOUT.TAG_PADDING} ${KB_LAYOUT.TAG_ROUNDED} ${KB_LAYOUT.TAG_TEXT} bg-gray-200 text-gray-800 border border-gray-200 mr-1`}>
                          {t('knowledgeBase.tag.chunks', { count: kb.chunkCount || 0 })}
                        </span>

                        {/* Knowledge base source tag */}
                        <span className={`inline-flex items-center ${KB_LAYOUT.TAG_PADDING} ${KB_LAYOUT.TAG_ROUNDED} ${KB_LAYOUT.TAG_TEXT} bg-gray-200 text-gray-800 border border-gray-200 mr-1`}>
                          {t('knowledgeBase.tag.source', { source: kb.source })}
                        </span>

                        {/* Creation date tag - only show date */}
                        <span className={`inline-flex items-center ${KB_LAYOUT.TAG_PADDING} ${KB_LAYOUT.TAG_ROUNDED} ${KB_LAYOUT.TAG_TEXT} bg-gray-200 text-gray-800 border border-gray-200 mr-1`}>
                          {t('knowledgeBase.tag.createdAt', { date: formatDate(kb.createdAt) })}
                        </span>

                        {/* Force line break */}
                        <div className={`w-full ${KB_LAYOUT.TAG_BREAK_HEIGHT}`}></div>

                        {/* Model tag - show normal or mismatch */}
                        <span className={`inline-flex items-center ${KB_LAYOUT.TAG_PADDING} ${KB_LAYOUT.TAG_ROUNDED} ${KB_LAYOUT.TAG_TEXT} ${KB_LAYOUT.SECOND_ROW_TAG_MARGIN} bg-green-100 text-green-800 border border-green-200 mr-1`}>
                          {t('knowledgeBase.tag.model', { model: getModelDisplayName(kb.embeddingModel) })}
                        </span>
                        {kb.embeddingModel !== "unknown" && kb.embeddingModel !== currentEmbeddingModel && (
                          <span className={`inline-flex items-center ${KB_LAYOUT.TAG_PADDING} ${KB_LAYOUT.TAG_ROUNDED} ${KB_LAYOUT.TAG_TEXT} ${KB_LAYOUT.SECOND_ROW_TAG_MARGIN} bg-yellow-100 text-yellow-800 border border-yellow-200 mr-1`}>
                            {t('knowledgeBase.tag.modelMismatch')}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        ) : (
          <div className={`${KB_LAYOUT.EMPTY_STATE_PADDING} text-center text-gray-500`}>
            {t('knowledgeBase.list.empty')}
          </div>
        )}
      </div>
    </div>
  );
};

export default KnowledgeBaseList;
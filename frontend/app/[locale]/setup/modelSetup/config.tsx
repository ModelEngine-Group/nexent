"use client"

import { useState, useEffect, useRef } from "react"
import { Typography, Row, Col } from "antd"
import { AppConfigSection } from './appConfig'
import { ModelConfigSection, ModelConfigSectionRef } from './modelConfig'
import { useTranslation } from 'react-i18next'
import { 
  SETUP_PAGE_CONTAINER, 
  TWO_COLUMN_LAYOUT, 
  STANDARD_CARD,
  CARD_HEADER 
} from '@/lib/layoutConstants'

const { Title } = Typography

// 添加接口定义
interface AppModelConfigProps {
  skipModelVerification?: boolean;
}

export default function AppModelConfig({ skipModelVerification = false }: AppModelConfigProps) {
  const { t } = useTranslation()
  const [isClientSide, setIsClientSide] = useState(false)
  const modelConfigRef = useRef<ModelConfigSectionRef | null>(null)

  // 添加useEffect钩子用于初始化加载配置
  useEffect(() => {
    setIsClientSide(true)
    
    return () => {
      setIsClientSide(false)
    }
  }, [skipModelVerification])

  return (
    <div className="w-full mx-auto" style={{ 
      maxWidth: SETUP_PAGE_CONTAINER.MAX_WIDTH,
      padding: `0 ${SETUP_PAGE_CONTAINER.HORIZONTAL_PADDING}`
    }}>
      {isClientSide ? (
        <div className="w-full">
          <Row gutter={TWO_COLUMN_LAYOUT.GUTTER}>
            <Col 
              xs={TWO_COLUMN_LAYOUT.LEFT_COLUMN.xs} 
              md={TWO_COLUMN_LAYOUT.LEFT_COLUMN.md} 
              lg={TWO_COLUMN_LAYOUT.LEFT_COLUMN.lg} 
              xl={TWO_COLUMN_LAYOUT.LEFT_COLUMN.xl} 
              xxl={TWO_COLUMN_LAYOUT.LEFT_COLUMN.xxl}
            >
              <div className={STANDARD_CARD.BASE_CLASSES} style={{ 
                height: SETUP_PAGE_CONTAINER.MAIN_CONTENT_HEIGHT,
                padding: STANDARD_CARD.PADDING,
                display: 'flex',
                flexDirection: 'column'
              }}>
                <div style={{ 
                  padding: CARD_HEADER.PADDING,
                  flexShrink: 0
                }}>
                  <Title level={4}>{t('setup.config.appSettings')}</Title>
                  <div className={CARD_HEADER.DIVIDER_CLASSES}></div>
                </div>
                <div style={{ 
                  flex: 1,
                  ...STANDARD_CARD.CONTENT_SCROLL
                }}>
                  <AppConfigSection />
                </div>
              </div>
            </Col>
            
            <Col 
              xs={TWO_COLUMN_LAYOUT.RIGHT_COLUMN.xs} 
              md={TWO_COLUMN_LAYOUT.RIGHT_COLUMN.md} 
              lg={TWO_COLUMN_LAYOUT.RIGHT_COLUMN.lg} 
              xl={TWO_COLUMN_LAYOUT.RIGHT_COLUMN.xl} 
              xxl={TWO_COLUMN_LAYOUT.RIGHT_COLUMN.xxl}
            >
              <div className={STANDARD_CARD.BASE_CLASSES} style={{ 
                height: SETUP_PAGE_CONTAINER.MAIN_CONTENT_HEIGHT,
                padding: STANDARD_CARD.PADDING,
                display: 'flex',
                flexDirection: 'column'
              }}>
                <div style={{ 
                  padding: CARD_HEADER.PADDING,
                  flexShrink: 0
                }}>
                  <Title level={4}>{t('setup.config.modelSettings')}</Title>
                  <div className={CARD_HEADER.DIVIDER_CLASSES}></div>
                </div>
                <div style={{ 
                  flex: 1,
                  background: "#fff",
                  ...STANDARD_CARD.CONTENT_SCROLL
                }}>
                  <ModelConfigSection ref={modelConfigRef as any} skipVerification={skipModelVerification} />
                </div>
              </div>
            </Col>
          </Row>
        </div>
      ) : (
        <div className="max-w-4xl mx-auto">
          <div className="h-[300px] flex items-center justify-center">
            <span>{t('common.loading')}</span>
          </div>
        </div>
      )}
    </div>
  )
}
"use client";

import { useState, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Typography, Row, Col } from "antd";

import {
  SETUP_PAGE_CONTAINER,
  TWO_COLUMN_LAYOUT,
  STANDARD_CARD,
  CARD_HEADER,
} from "@/const/layoutConstants";

import { AppConfigSection } from "./components/appConfig";
import {
  ModelConfigSection,
  ModelConfigSectionRef,
} from "./components/modelConfig";

const { Title } = Typography;

// Add interface definition
interface AppModelConfigProps {
  skipModelVerification?: boolean;
  // Expose a ref from parent to allow programmatic dropdown change
  forwardedRef?: React.Ref<ModelConfigSectionRef>;
}

export default function AppModelConfig({
  skipModelVerification = false,
  forwardedRef,
}: AppModelConfigProps) {
  const { t } = useTranslation();
  const [isClientSide, setIsClientSide] = useState(false);
  const modelConfigRef = useRef<ModelConfigSectionRef | null>(null);

  // Add useEffect hook for initial configuration loading
  useEffect(() => {
    setIsClientSide(true);

    return () => {
      setIsClientSide(false);
    };
  }, [skipModelVerification]);

  // Bridge internal ref to external forwardedRef so parent can call simulateDropdownChange
  useEffect(() => {
    if (!forwardedRef) return;
    if (typeof forwardedRef === "function") {
      forwardedRef(modelConfigRef.current);
    } else {
      // @ts-ignore allow writing current
      (forwardedRef as any).current = modelConfigRef.current;
    }
  }, [forwardedRef]);

  return (
    <div
      className="w-full h-full mx-auto"
      style={{
        maxWidth: SETUP_PAGE_CONTAINER.MAX_WIDTH,
        padding: `0 ${SETUP_PAGE_CONTAINER.HORIZONTAL_PADDING}`,
      }}
    >
      {isClientSide ? (
        <div className="w-full h-full">
          <Row className="h-full w-full" gutter={TWO_COLUMN_LAYOUT.GUTTER}>
            <Col
              className="h-full"
              xs={TWO_COLUMN_LAYOUT.LEFT_COLUMN.xs}
              md={TWO_COLUMN_LAYOUT.LEFT_COLUMN.md}
              lg={TWO_COLUMN_LAYOUT.LEFT_COLUMN.lg}
              xl={TWO_COLUMN_LAYOUT.LEFT_COLUMN.xl}
              xxl={TWO_COLUMN_LAYOUT.LEFT_COLUMN.xxl}
            >
              <div
                className={`${STANDARD_CARD.BASE_CLASSES} flex flex-col h-full w-full`}
                style={{
                  padding: STANDARD_CARD.PADDING,
                }}
              >
                <div
                  style={{
                    padding: CARD_HEADER.PADDING,
                    flexShrink: 0,
                  }}
                >
                  <Title level={4}>{t("setup.config.appSettings")}</Title>
                  <div className={CARD_HEADER.DIVIDER_CLASSES}></div>
                </div>
                <div
                  style={{
                    flex: 1,
                    ...STANDARD_CARD.CONTENT_SCROLL,
                  }}
                >
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
              <div
                className={`${STANDARD_CARD.BASE_CLASSES} flex flex-col h-full w-full`}
                style={{
                  padding: STANDARD_CARD.PADDING,
                }}
              >
                <div
                  style={{
                    padding: CARD_HEADER.PADDING,
                    flexShrink: 0,
                  }}
                >
                  <Title level={4}>{t("setup.config.modelSettings")}</Title>
                  <div className={CARD_HEADER.DIVIDER_CLASSES}></div>
                </div>
                <div
                  style={{
                    flex: 1,
                    background: "#fff",
                    ...STANDARD_CARD.CONTENT_SCROLL,
                  }}
                >
                  <ModelConfigSection
                    ref={modelConfigRef as any}
                    skipVerification={skipModelVerification}
                  />
                </div>
              </div>
            </Col>
          </Row>
        </div>
      ) : (
        <div className="max-w-4xl mx-auto">
          <div className="h-[300px] flex items-center justify-center">
            <span>{t("common.loading")}</span>
          </div>
        </div>
      )}
    </div>
  );
}

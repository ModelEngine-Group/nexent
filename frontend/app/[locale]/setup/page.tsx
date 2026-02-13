"use client";

import { useState } from "react";
import { Steps, Button } from "antd";
import { ChevronLeft, ChevronRight, Check } from "lucide-react";
import { useSetupFlow } from "@/hooks/useSetupFlow";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useDeployment } from "@/components/providers/deploymentProvider";
import ModelsContent from "../models/page";
import KnowledgesContent from "../knowledges/page";
import AgentSetupOrchestrator from "../agents/page";

type SetupStep = "models" | "knowledges" | "agents";

export default function SetupPage() {
  const { t, router } = useSetupFlow({});

  // Get auth state directly from providers
  const { isSpeedMode } = useDeployment();
  const { user } = useAuthorizationContext();

  const [currentStepIndex, setCurrentStepIndex] = useState<number>(0);
  const [isSaving, setIsSaving] = useState(false);

  const steps = [
    {
      key: "models" as SetupStep,
      title: t("setup.model.description"),
    },
    {
      key: "knowledges" as SetupStep,
      title: t("setup.knowledge.description"),
    },
    {
      key: "agents" as SetupStep,
      title: t("setup.agent.description"),
    },
  ];

  const [completed, setCompleted] = useState<boolean[]>(
    new Array(steps.length).fill(false)
  );

  const currentStep = steps[currentStepIndex];
  const isFirstStep = currentStepIndex === 0;
  const isLastStep = currentStepIndex === steps.length - 1;

  const handleNext = () => {
    // mark current as completed then advance (unless last)
    setCompleted((prev) => {
      const next = [...prev];
      next[currentStepIndex] = true;
      return next;
    });
    if (!isLastStep) {
      setCurrentStepIndex((i) => i + 1);
    } else {
      // last step -> complete
      router.push("/chat");
    }
  };

  const handleBack = () => {
    if (!isFirstStep) {
      // Mark current step as incomplete when going back
      setCompleted((prev) => {
        const next = [...prev];
        next[currentStepIndex - 1] = false;
        return next;
      });
      setCurrentStepIndex((i) => i - 1);
    }
  };

  const handleComplete = () => {
    router.push("/chat");
  };

  const renderStepContent = () => {
    switch (currentStep.key) {
      case "models":
        return <ModelsContent />;
      case "knowledges":
        return <KnowledgesContent />;
      case "agents":
        return <AgentSetupOrchestrator />;
      default:
        return null;
    }
  };


  return (
    <div className="w-full h-full flex flex-col bg-slate-50 dark:bg-slate-900 font-sans overflow-hidden">
      {/* Top fixed Steps bar */}
      <div className="bg-white dark:bg-slate-900 border-b z-50">
        <div className="max-w-[1800px] mx-auto px-8 py-6">
          <Steps
            current={currentStepIndex}
            onChange={(idx) => {
              // allow jumping only to already completed steps or current
              if (idx <= currentStepIndex || completed[idx]) {
                setCurrentStepIndex(idx);
              }
            }}
            size="default"
            items={steps.map((s, i) => ({
              title: s.title,
              status: completed[i]
                ? "finish"
                : i === currentStepIndex
                  ? "process"
                  : "wait",
              icon: completed[i] ? <Check className="w-4 h-4" /> : undefined,
            }))}
          />
        </div>
      </div>

      {/* Main container*/}
      <div className="flex:1 min-h-0 h-full w-full">
        {/* Main Content area */}
        {renderStepContent()}
      </div>

      {/* Bottom fixed action bar */}
      <div className="bg-white dark:bg-slate-900 border-t z-50">
        <div className="mx-auto px-8 py-4 flex justify-end gap-4">
          <Button
            onClick={handleBack}
            disabled={isFirstStep}
            type="default"
            className="px-4 py-2 rounded-lg h-10 flex items-center gap-2 border border-gray-200 bg-white text-gray-700"
            icon={<ChevronLeft className="w-4 h-4" />}
          >
            {t("setup.navigation.button.previous")}
          </Button>
          {!isLastStep ? (
            <Button
              type="primary"
              onClick={handleNext}
              className="px-4 py-2 rounded-lg h-10 flex items-center gap-2 shadow-md"
              icon={<ChevronRight className="w-4 h-4 text-white" />}
            >
              {t("setup.navigation.button.next")}
            </Button>
          ) : (
            <Button
              type="primary"
              onClick={handleComplete}
              loading={isSaving}
              className="px-4 py-2 rounded-lg h-10 flex items-center gap-2 shadow-md"
              icon={<Check className="w-4 h-4 text-white" />}
            >
              {t("setup.navigation.button.complete")}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

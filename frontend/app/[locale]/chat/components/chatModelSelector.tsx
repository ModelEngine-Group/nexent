"use client";

import React, { useState, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { ChevronDown, Cpu } from "lucide-react";

interface ChatModelSelectorProps {
  modelIds: number[];
  modelNames: string[];
  selectedModelId: number | null;
  onModelSelect: (modelId: number | null) => void;
  disabled?: boolean;
}

export function ChatModelSelector({
  modelIds,
  modelNames,
  selectedModelId,
  onModelSelect,
  disabled = false,
}: ChatModelSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [dropdownPosition, setDropdownPosition] = useState({
    top: 0,
    left: 0,
    direction: "down" as "up" | "down",
  });
  const [isPositionCalculated, setIsPositionCalculated] = useState(false);
  const buttonRef = useRef<HTMLDivElement>(null);
  const { t } = useTranslation("common");

  const selectedModelName = modelIds.includes(selectedModelId ?? -1)
    ? modelNames[modelIds.indexOf(selectedModelId!)]
    : null;

  useEffect(() => {
    if (isOpen && buttonRef.current) {
      const buttonRect = buttonRef.current.getBoundingClientRect();
      const viewportHeight = window.innerHeight;
      const dropdownHeight = Math.min(modelIds.length * 40 + 16, 200);

      const hasSpaceBelow = buttonRect.bottom + dropdownHeight + 10 < viewportHeight;
      const hasSpaceAbove = buttonRect.top - dropdownHeight - 10 > 0;

      let direction: "up" | "down" = "up";
      let top = buttonRect.top - 4;

      if (!hasSpaceAbove && hasSpaceBelow) {
        direction = "down";
        top = buttonRect.bottom + 4;
      }

      setDropdownPosition({
        top,
        left: buttonRect.left,
        direction,
      });
      setIsPositionCalculated(true);
    } else if (!isOpen) {
      setIsPositionCalculated(false);
    }
  }, [isOpen, modelIds.length]);

  useEffect(() => {
    if (!isOpen) return;

    const handleScroll = () => setIsOpen(false);
    const handleResize = () => setIsOpen(false);

    window.addEventListener("scroll", handleScroll, true);
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("scroll", handleScroll, true);
      window.removeEventListener("resize", handleResize);
    };
  }, [isOpen]);

  const handleModelSelect = (modelId: number | null) => {
    onModelSelect(modelId);
    setIsOpen(false);
  };

  if (modelIds.length === 0) {
    return null;
  }

  return (
    <div className="relative">
      <div
        ref={buttonRef}
        className={`
          relative h-8 min-w-[120px] max-w-[200px] px-2
          rounded-lg border border-slate-200
          bg-white hover:bg-slate-50
          flex items-center justify-between
          cursor-pointer select-none
          transition-colors duration-150
          ${disabled ? "opacity-50 cursor-not-allowed" : ""}
          ${
            isOpen
              ? "border-blue-400 ring-2 ring-blue-100"
              : "hover:border-slate-300"
          }
        `}
        onClick={() => !disabled && setIsOpen(!isOpen)}
      >
        <div className="flex items-center gap-2 truncate">
          {selectedModelId && (
            <Cpu className="w-4 h-4 text-blue-500 flex-shrink-0" />
          )}
          <span
            className={`truncate text-sm ${
              selectedModelId ? "font-medium text-slate-700" : "text-slate-500"
            }`}
          >
            {selectedModelName || t("chatInput.selectModel")}
          </span>
        </div>
        <ChevronDown
          className={`h-4 w-4 text-slate-400 transition-transform duration-200 ${
            isOpen ? "rotate-180" : ""
          }`}
        />
      </div>

      {isOpen && isPositionCalculated && typeof window !== "undefined" && createPortal(
        <>
          {/* Overlay */}
          <div
            className="fixed inset-0 z-[9998]"
            onClick={() => setIsOpen(false)}
          />

          {/* Dropdown */}
          <div
            className="fixed bg-white border border-slate-200 rounded-md shadow-lg z-[9999] max-h-48 overflow-y-auto"
            style={{
              top:
                dropdownPosition.direction === "up"
                  ? `${dropdownPosition.top}px`
                  : `${dropdownPosition.top}px`,
              left: `${dropdownPosition.left}px`,
              width: `250px`,
              transform:
                dropdownPosition.direction === "up"
                  ? "translateY(-100%)"
                  : "none",
            }}
          >
            <div className="py-1">
              {modelIds.map((modelId, idx) => (
                <div
                  key={modelId}
                  className={`
                    flex items-center gap-3 px-3 py-2 text-sm
                    transition-all duration-150 ease-in-out
                    ${
                      selectedModelId === modelId
                        ? "bg-blue-50/70 text-blue-600 cursor-pointer"
                        : "hover:bg-slate-50 cursor-pointer text-slate-700"
                    }
                    ${idx !== 0 ? "border-t border-slate-100" : ""}
                  `}
                  onClick={() => handleModelSelect(modelId)}
                >
                  <Cpu
                    className={`h-4 w-4 flex-shrink-0 ${
                      selectedModelId === modelId ? "text-blue-500" : "text-slate-400"
                    }`}
                  />
                  <span className="truncate text-sm">{modelNames[idx]}</span>
                </div>
              ))}
            </div>
          </div>
        </>,
        document.body
      )}
    </div>
  );
}

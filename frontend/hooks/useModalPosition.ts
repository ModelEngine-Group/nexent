import { useState, useEffect } from "react";

/**
 * Custom hook for managing modal position and window dimensions
 * Used for positioning tool test panels relative to main modals
 */
export const useModalPosition = (isOpen: boolean) => {
  const [windowWidth, setWindowWidth] = useState<number>(0);
  const [mainModalTop, setMainModalTop] = useState<number>(0);
  const [mainModalRight, setMainModalRight] = useState<number>(0);

  // Monitor window width for responsive positioning
  useEffect(() => {
    const handleResize = () => {
      setWindowWidth(window.innerWidth);
    };

    // Set initial width
    setWindowWidth(window.innerWidth);

    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  // Calculate main modal position for tool test panel alignment
  useEffect(() => {
    if (!isOpen) return;

    const calculateMainModalPosition = () => {
      const modalElement = document.querySelector(".ant-modal");
      if (modalElement) {
        const rect = modalElement.getBoundingClientRect();
        setMainModalTop(rect.top);
        setMainModalRight(rect.right);
      }
    };

    // Delay calculation to ensure Modal is rendered
    const timeoutId = setTimeout(calculateMainModalPosition, 100);

    // Use ResizeObserver to track modal size changes
    const observer = new ResizeObserver((entries) => {
      for (let entry of entries) {
        const rect = entry.target.getBoundingClientRect();
        setMainModalTop(rect.top);
        setMainModalRight(rect.right);
      }
    });

    const modalElement = document.querySelector(".ant-modal");
    if (modalElement) {
      observer.observe(modalElement);
    }

    return () => {
      clearTimeout(timeoutId);
      observer.disconnect();
    };
  }, [isOpen]);

  return {
    windowWidth,
    mainModalTop,
    mainModalRight,
  };
};

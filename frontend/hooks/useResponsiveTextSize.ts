import { useState, useRef, useEffect } from "react";

// Custom Hook - Dynamically adjust font size based on text content
export const useResponsiveTextSize = (text: string, containerWidth: number, maxFontSize: number = 24) => {
    const [fontSize, setFontSize] = useState(maxFontSize);
    const textRef = useRef<HTMLHeadingElement>(null);
    
    useEffect(() => {
      if (!textRef.current) return;
      
      const adjustFontSize = () => {
        const element = textRef.current;
        if (!element) return;
        
        // Start trying from maximum font size
        let currentSize = maxFontSize;
        element.style.fontSize = `${currentSize}px`;
        
        // If text overflows, reduce font size until it fits
        while (element.scrollWidth > containerWidth && currentSize > 12) {
          currentSize -= 1;
          element.style.fontSize = `${currentSize}px`;
        }
        
        setFontSize(currentSize);
      };
      
      // Initial adjustment
      adjustFontSize();
      
      // Listen for window size changes
      window.addEventListener('resize', adjustFontSize);
      
      return () => {
        window.removeEventListener('resize', adjustFontSize);
      };
    }, [text, containerWidth, maxFontSize]);
    
    return { textRef, fontSize };
  };
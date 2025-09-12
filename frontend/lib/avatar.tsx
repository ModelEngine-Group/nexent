import { createAvatar } from '@dicebear/core';
import * as iconStyle from '@dicebear/icons';

import { presetIcons } from "@/const/avatar"
import log from "@/lib/logger";
import type { AppConfig } from '@/types/modelConfig';

// Seeded random number generator
class SeededRandom {
  private seed: number;

  constructor(seed: string) {
    // Convert string to numeric seed
    this.seed = Array.from(seed).reduce((acc, char) => {
      return acc + char.charCodeAt(0);
    }, 0);
  }

  // Generate random number between 0 and 1
  random(): number {
    const x = Math.sin(this.seed++) * 10000;
    return x - Math.floor(x);
  }

  // Generate random integer within specified range
  randomInt(min: number, max: number): number {
    return Math.floor(this.random() * (max - min + 1)) + min;
  }
}

// Directly generate avatar URI and return
export const generateAvatarUri = (icon: string, color: string, size: number = 30, scale: number = 80): string => {
  const selectedIcon = presetIcons.find(preset => preset.key === icon) || presetIcons[0];
  const mainColor = color.replace("#", "");
  const secondaryColor = generateComplementaryColor(mainColor);
  
  const avatar = createAvatar(iconStyle, {
    seed: selectedIcon.icon,
    backgroundColor: [mainColor, secondaryColor],
    backgroundType: ["gradientLinear"], 
    icon: [selectedIcon.key],
    scale: scale,
    size: size,
    radius: 50
  });
  
  return avatar.toDataUri();
};

// Helper function to get avatar URL based on configuration
export const getAvatarUrl = (config: AppConfig, size: number = 30, scale: number = 80): string => {
  if (config.iconType === "custom" && config.customIconUrl) {
    // Return custom image URL
    return config.customIconUrl;
  } else if (config.avatarUri) {
    // If pre-generated URI exists, return directly
    return config.avatarUri;
  } else {
    // Default return first preset icon
    const defaultIcon = presetIcons[0];
    const mainColor = "2689cb";
    const secondaryColor = generateComplementaryColor(mainColor);

    const avatar = createAvatar(iconStyle, {
      seed: mainColor,
      backgroundColor: [mainColor, secondaryColor],
      backgroundType: ["gradientLinear"], 
      icon: [defaultIcon.key],
      scale: scale,
      size: size,
      radius: 50
    });

    return avatar.toDataUri();
  }
};

/**
 * Generate random complementary color based on main color
 * @param mainColor Main color (hex color value, with or without # prefix)
 * @returns Generated secondary color (hex color value, without # prefix)
 */
export const generateComplementaryColor = (mainColor: string): string => {
  // Remove possible # prefix
  const colorHex = mainColor.replace('#', '');
  
  // Convert hex color to RGB
  const r = parseInt(colorHex.substring(0, 2), 16);
  const g = parseInt(colorHex.substring(2, 4), 16);
  const b = parseInt(colorHex.substring(4, 6), 16);
  
  // Use color value as random number seed
  const random = new SeededRandom(colorHex);
  
  // Generate random variation direction (several common variation patterns)
  const variation = random.randomInt(0, 3);
  
  let newR = r, newG = g, newB = b;
  
  switch(variation) {
    case 0: // Darken - generate darker color
      newR = Math.max(0, r - 40 - random.randomInt(0, 30));
      newG = Math.max(0, g - 40 - random.randomInt(0, 30));
      newB = Math.max(0, b - 40 - random.randomInt(0, 30));
      break;
    case 1: // Brighten - generate brighter color
      newR = Math.min(255, r + 40 + random.randomInt(0, 30));
      newG = Math.min(255, g + 40 + random.randomInt(0, 30));
      newB = Math.min(255, b + 40 + random.randomInt(0, 30));
      break;
    case 2: // Similar color - fine-tune one or two RGB channels
      const channel = random.randomInt(0, 2);
      if (channel === 0) {
        newR = Math.min(255, Math.max(0, r + random.randomInt(0, 120) - 60));
      } else if (channel === 1) {
        newG = Math.min(255, Math.max(0, g + random.randomInt(0, 120) - 60));
      } else {
        newB = Math.min(255, Math.max(0, b + random.randomInt(0, 120) - 60));
      }
      break;
    case 3: // HSL adjustment - convert to HSL then adjust hue
      const [h, s, l] = rgbToHsl(r, g, b);
      const newH = (h + 0.05 + random.random() * 0.2) % 1; // Adjust hue ±30-90 degrees
      const [adjR, adjG, adjB] = hslToRgb(newH, s, l);
      newR = adjR;
      newG = adjG;
      newB = adjB;
      break;
  }
  
  // Ensure RGB values are within valid range
  newR = Math.min(255, Math.max(0, Math.round(newR)));
  newG = Math.min(255, Math.max(0, Math.round(newG)));
  newB = Math.min(255, Math.max(0, Math.round(newB)));
  
  // Convert back to hexadecimal
  return ((1 << 24) + (newR << 16) + (newG << 8) + newB).toString(16).slice(1);
}

// Helper function: RGB to HSL
function rgbToHsl(r: number, g: number, b: number): [number, number, number] {
  r /= 255;
  g /= 255;
  b /= 255;
  
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  let h = 0, s = 0, l = (max + min) / 2;
  
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    
    switch(max) {
      case r: h = (g - b) / d + (g < b ? 6 : 0); break;
      case g: h = (b - r) / d + 2; break;
      case b: h = (r - g) / d + 4; break;
    }
    
    h /= 6;
  }
  
  return [h, s, l];
}

// Helper function: HSL to RGB
function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  let r, g, b;
  
  if (s === 0) {
    r = g = b = l; // Gray
  } else {
    const hue2rgb = (p: number, q: number, t: number) => {
      if (t < 0) t += 1;
      if (t > 1) t -= 1;
      if (t < 1/6) return p + (q - p) * 6 * t;
      if (t < 1/2) return q;
      if (t < 2/3) return p + (q - p) * (2/3 - t) * 6;
      return p;
    };
    
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
    const p = 2 * l - q;
    
    r = hue2rgb(p, q, h + 1/3);
    g = hue2rgb(p, q, h);
    b = hue2rgb(p, q, h - 1/3);
  }
  
  return [Math.round(r * 255), Math.round(g * 255), Math.round(b * 255)];
}

/**
 * Extract main and secondary colors from Dicebear generated Data URI, reserved for app name use
 * @param dataUri Dicebear generated avatar data URI
 * @returns Object containing mainColor and secondaryColor, color values without # prefix
 */
export const extractColorsFromUri = (dataUri: string): { mainColor: string | null, secondaryColor: string | null } =>  {
  // Default return value
  const result = { 
    mainColor: "", 
    secondaryColor: "" 
  };
  
  try {
    // Check if it's a Data URI
    if (!dataUri || !dataUri.startsWith('data:')) {
      return result;
    }
    
    // Extract Base64 or URL encoded content
    let svgContent = '';
    if (dataUri.includes('base64')) {
      // Handle Base64 encoding
      const base64Content = dataUri.split(',')[1];
      svgContent = atob(base64Content); // Decode Base64
    } else {
      // Handle URL encoding
      const uriContent = dataUri.split(',')[1];
      svgContent = decodeURIComponent(uriContent);
    }
    
    // Find linear gradient definition
    const gradientMatch = svgContent.match(/<linearGradient[^>]*>([\s\S]*?)<\/linearGradient>/);
    if (!gradientMatch) {
      // If no gradient, find background fill color
      const fillMatch = svgContent.match(/fill="(#[0-9a-fA-F]{6})"/);
      if (fillMatch && fillMatch[1]) {
        result.mainColor = fillMatch[1].replace('#', '');
      }
      return result;
    }
    
    // Extract colors from gradient
    const stopMatches = svgContent.matchAll(/<stop[^>]*stop-color="(#[0-9a-fA-F]{6})"[^>]*>/g);
    const colors: string[] = [];
    
    for (const match of stopMatches) {
      if (match[1]) {
        colors.push(match[1].replace('#', ''));
      }
    }
    
    // Usually first is main color, second is secondary color
    if (colors.length >= 1) {
      result.mainColor = colors[0];
    }
    if (colors.length >= 2) {
      result.secondaryColor = colors[1];
    }
    
  } catch (error) {
    log.error('Error extracting colors:', error);
  }
  
  return result;
}
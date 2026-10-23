import { Slider } from "antd";
import { useTranslation } from "react-i18next";

// Default chunk size values (matching backend defaults)
export const DEFAULT_EXPECTED_CHUNK_SIZE = 1024;
export const DEFAULT_MAXIMUM_CHUNK_SIZE = 1536;

interface ModelChunkSizeSliderProps {
  value: [number, number];
  onChange: (value: [number, number]) => void;
  disabled?: boolean;
}

export const ModelChunkSizeSlider = ({
  value,
  onChange,
  disabled = false,
}: ModelChunkSizeSliderProps) => {
  const { t } = useTranslation();
  // Build dynamic marks to avoid overlap when handles are close
  const getChunkSizeMarks = (): Record<number, React.ReactNode> => {
    const [left, right] = value;
    const distance = right - left;
    // If handles are close, render a single combined label at the midpoint
    if (distance <= 128) {
      const mid = Math.round((left + right) / 2);
      return { [mid]: `${left} - ${right}` };
    }
    // Otherwise render two separate labels
    return {
      [left]: `${left}`,
      [right]: `${right}`,
    };
  };

  return (
    <Slider
      range
      min={128}
      max={4096}
      marks={getChunkSizeMarks()}
      step={128}
      value={value}
      onChange={(sliderValue) => {
        if (Array.isArray(sliderValue) && sliderValue.length === 2) {
          onChange([sliderValue[0], sliderValue[1]] as [number, number]);
        }
      }}
      disabled={disabled}
      tooltip={{
        formatter: (val?: number) => {
          if (val === undefined) return "";
          const [left, right] = value;
          if (val === left) return `${t("modelConfig.slider.expectedChunkSize")}: ${val}`;
          if (val === right) return `${t("modelConfig.slider.maximumChunkSize")}: ${val}`;
          return `${val}`;
        },
      }}
    />
  );
};


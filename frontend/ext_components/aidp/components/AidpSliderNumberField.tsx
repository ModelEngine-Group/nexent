import React from "react";
import { InputNumber, Slider } from "antd";

import styles from "./AidpCreateKbSections.module.css";

interface AidpSliderNumberFieldProps {
  value?: number | null;
  onChange?: (value: number | null) => void;
  min: number;
  max: number;
  step: number;
  unit?: string;
  precision?: number;
  marks: Record<number, string>;
  ariaLabel: string;
}

const AidpSliderNumberField: React.FC<AidpSliderNumberFieldProps> = ({
  value,
  onChange,
  min,
  max,
  step,
  unit,
  precision,
  marks,
  ariaLabel,
}) => {
  const safeValue = typeof value === "number" ? value : min;

  return (
    <div className="w-full">
      <div className="flex w-full items-start gap-4">
        <div className={styles.sliderTrackGroup}>
          <Slider
            className="min-w-0 flex-1"
            min={min}
            max={max}
            step={step}
            value={safeValue}
            tooltip={{
              formatter: (sliderValue) => `${sliderValue}${unit || ""}`,
            }}
            onChange={(nextValue) => onChange?.(nextValue)}
            aria-label={ariaLabel}
          />
          <div className={styles.sliderMarks}>
            <span>{marks[min]}</span>
            <span>{marks[max]}</span>
          </div>
        </div>
        <div className={styles.sliderValueGroup}>
          <InputNumber
            aria-label={ariaLabel}
            className={styles.sliderValueInput}
            min={min}
            max={max}
            step={step}
            precision={precision}
            controls={false}
            value={value}
            onChange={onChange}
          />
          <span className={styles.sliderUnit}>{unit || ""}</span>
        </div>
      </div>
    </div>
  );
};

export default AidpSliderNumberField;

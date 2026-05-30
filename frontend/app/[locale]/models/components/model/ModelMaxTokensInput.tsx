import { AutoComplete, Input } from "antd";

const MAX_TOKEN_OPTIONS = [
  { value: "4096", label: "4K / 4,096" },
  { value: "8192", label: "8K / 8,192" },
  { value: "16384", label: "16K / 16,384" },
  { value: "32768", label: "32K / 32,768" },
  { value: "65536", label: "64K / 65,536" },
  { value: "131072", label: "128K / 131,072" },
  { value: "200000", label: "200K / 200,000" },
  { value: "1000000", label: "1M / 1,000,000" },
];

interface ModelMaxTokensInputProps {
  id?: string;
  value: string;
  placeholder?: string;
  onChange: (value: string) => void;
}

export const isValidMaxTokens = (value: string): boolean => {
  const trimmed = value.trim();
  return /^[1-9]\d*$/.test(trimmed);
};

export const parseMaxTokens = (value: string): number | undefined => {
  return isValidMaxTokens(value) ? parseInt(value.trim(), 10) : undefined;
};

export const ModelMaxTokensInput = ({
  id,
  value,
  placeholder,
  onChange,
}: ModelMaxTokensInputProps) => {
  return (
    <AutoComplete
      className="w-full"
      value={value}
      options={MAX_TOKEN_OPTIONS}
      placeholder={placeholder}
      onChange={onChange}
      filterOption={(inputValue, option) =>
        String(option?.label ?? "")
          .toLowerCase()
          .includes(inputValue.toLowerCase()) ||
        String(option?.value ?? "").includes(inputValue)
      }
    >
      <Input id={id} inputMode="numeric" pattern="[0-9]*" />
    </AutoComplete>
  );
};

import { X } from "lucide-react";

export interface StandardCloseButtonProps {
  ariaLabel: string;
  onClick: () => void;
}

export function StandardCloseButton({
  ariaLabel,
  onClick,
}: StandardCloseButtonProps) {
  return (
    <button
      type="button"
      aria-label={ariaLabel}
      className="flex h-[14px] w-[14px] shrink-0 cursor-pointer items-center justify-center border-0 bg-transparent p-0 focus:outline-none"
      onClick={onClick}
    >
      <X size={14} />
    </button>
  );
}

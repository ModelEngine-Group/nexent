import { BRANDING } from "@/const/branding";

interface HospitalBrandMarkProps {
  title: string;
  subtitle?: string;
  className?: string;
}

export function HospitalBrandMark({
  title,
  subtitle,
  className = "",
}: HospitalBrandMarkProps) {
  return (
    <div
      className={`flex flex-wrap items-center justify-center gap-x-12 md:gap-x-16 gap-y-4 ${className}`}
    >
      <div className="flex items-center gap-4">
        <img
          src={BRANDING.heroLogoSrc}
          alt=""
          aria-hidden="true"
          className="h-16 w-16 md:h-20 md:w-20 lg:h-24 lg:w-24 object-contain"
        />
        <span className="font-hospital-title text-4xl text-slate-900 dark:text-white md:text-5xl lg:text-6xl">
          {title}
        </span>
      </div>
      {subtitle ? (
        <span className="text-3xl font-bold text-hospital-red md:text-4xl lg:text-5xl">
          {subtitle}
        </span>
      ) : null}
    </div>
  );
}

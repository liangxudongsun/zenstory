import React from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "../../lib/utils";

interface AdminSelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  fullWidth?: boolean;
  wrapperClassName?: string;
}

const baseSelectClasses =
  "min-h-11 appearance-none rounded-lg border border-[hsl(var(--border-color))] bg-[hsl(var(--bg-primary))] px-3 py-2.5 pr-9 text-base md:text-sm text-[hsl(var(--text-primary))] transition-colors focus:outline-none focus:ring-2 focus:ring-[hsl(var(--accent-primary)/0.45)] hover:border-[hsl(var(--border-hover))] disabled:cursor-not-allowed disabled:opacity-50";

export const AdminSelect = React.forwardRef<HTMLSelectElement, AdminSelectProps>(
  ({ fullWidth = false, wrapperClassName, className, children, ...props }, ref) => (
    <div className={cn("relative", fullWidth && "w-full", wrapperClassName)}>
      <select
        ref={ref}
        className={cn(baseSelectClasses, fullWidth && "w-full", className)}
        {...props}
      >
        {children}
      </select>
      <ChevronDown
        size={16}
        aria-hidden="true"
        className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[hsl(var(--text-secondary))]"
      />
    </div>
  ),
);

AdminSelect.displayName = "AdminSelect";

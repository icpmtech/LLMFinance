import type { LabelHTMLAttributes, ReactNode } from "react";

export function Label({ children, className = "", ...props }: LabelHTMLAttributes<HTMLLabelElement> & { children: ReactNode }) {
  return (
    <label className={`text-sm font-medium text-foreground ${className}`} {...props}>
      {children}
    </label>
  );
}

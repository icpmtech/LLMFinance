type BadgeVariant = "default" | "success" | "warning" | "info" | "danger" | "outline" | "secondary";

const secondaryClass = "bg-secondary text-secondary-foreground border border-border";

interface BadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
  className?: string;
}

const variants: Record<BadgeVariant, string> = {
  default: "bg-muted text-muted-foreground",
  success: "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30",
  warning: "bg-amber-500/15 text-amber-400 border border-amber-500/30",
  info: "bg-sky-500/15 text-sky-400 border border-sky-500/30",
  danger: "bg-red-500/15 text-red-400 border border-red-500/30",
  outline: "bg-transparent border border-border text-muted-foreground",
  secondary: secondaryClass,
};

export function Badge({ children, variant = "default", className = "" }: BadgeProps) {
  return (
    <span
      className={`
        inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium
        ${variants[variant]} ${className}
      `}
    >
      {children}
    </span>
  );
}

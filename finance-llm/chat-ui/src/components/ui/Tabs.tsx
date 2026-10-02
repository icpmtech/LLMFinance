import type { ReactNode } from "react";

export function Tabs({
  value,
  children,
  className = "",
}: {
  value: string;
  onValueChange?: (v: string) => void;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div data-tabs={value} className={className}>
      {children}
    </div>
  );
}

export function TabsList({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`inline-flex gap-1 rounded-xl border bg-muted p-1 ${className}`}>
      {children}
    </div>
  );
}

export function TabsTrigger({
  active,
  onClick,
  children,
  className = "",
}: {
  value: string;
  active?: boolean;
  onClick?: () => void;
  children: ReactNode;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-3 py-1.5 text-sm font-medium transition rounded-lg ${active ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"} ${className}`}
    >
      {children}
    </button>
  );
}

export function TabsContent({
  active,
  children,
  className = "",
}: {
  value: string;
  active?: boolean;
  children: ReactNode;
  className?: string;
}) {
  if (!active) return null;
  return <div className={className}>{children}</div>;
}

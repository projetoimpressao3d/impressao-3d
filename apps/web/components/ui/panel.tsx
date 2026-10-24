import React from "react";

interface PanelProps {
  children: React.ReactNode;
  className?: string;
}

export function Panel({ children, className = "" }: PanelProps) {
  return (
    <div
      className={`rounded-xl border border-zinc-800 bg-zinc-900 ${className}`}
    >
      {children}
    </div>
  );
}

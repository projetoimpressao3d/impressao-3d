import React from "react";

interface BadgeProps {
  children: React.ReactNode;
  variant?: "new" | "beta" | "pro" | "default";
  className?: string;
}

export function Badge({
  children,
  variant = "default",
  className = "",
}: BadgeProps) {
  const variants = {
    new: "bg-blue-600 text-white",
    beta: "bg-emerald-600/20 text-emerald-400 border border-emerald-500/40",
    pro: "bg-amber-500/20 text-amber-500 border border-amber-500/40",
    default: "bg-zinc-800 text-zinc-300 border border-zinc-700",
  };

  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold ${variants[variant]} ${className}`}
    >
      {children}
    </span>
  );
}

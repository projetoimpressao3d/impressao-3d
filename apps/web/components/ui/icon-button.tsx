import React from "react";

interface IconButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  children: React.ReactNode;
  active?: boolean;
}

export function IconButton({
  children,
  active = false,
  className = "",
  ...props
}: IconButtonProps) {
  return (
    <button
      type="button"
      className={`flex items-center justify-center rounded-lg p-2 transition-colors ${
        active
          ? "border border-emerald-500/50 bg-emerald-600/20 text-emerald-500"
          : "border border-zinc-800 bg-zinc-900 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
      } ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

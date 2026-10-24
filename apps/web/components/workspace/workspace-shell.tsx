"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { Badge } from "@/components/ui/badge";
import { IconButton } from "@/components/ui/icon-button";

export type SidebarTabId = "build-plate" | "models" | "smart-split";

interface WorkspaceShellProps {
  userEmail: string;
  userPlan?: "free" | "pro";
}

const MENU_ITEMS: {
  id: SidebarTabId;
  label: string;
  badge?: string;
  icon: React.ReactNode;
}[] = [
  {
    id: "build-plate",
    label: "Mesa de Trabalho",
    icon: (
      <svg
        className="h-4 w-4 shrink-0"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={1.8}
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z"
        />
      </svg>
    ),
  },
  {
    id: "models",
    label: "Modelos",
    icon: (
      <svg
        className="h-4 w-4 shrink-0"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={1.8}
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"
        />
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M3.27 6.96L12 12.01l8.73-5.05M12 22.08V12"
        />
      </svg>
    ),
  },
  {
    id: "smart-split",
    label: "Divisão Inteligente de Modelos",
    badge: "New",
    icon: (
      <svg
        className="h-4 w-4 shrink-0"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={1.8}
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M14.121 14.121L19 19m-7-7l7-7m-7 7l-2.879 2.879M12 12L9.121 9.121m0 5.758a3 3 0 10-4.243 4.243 3 3 0 004.243-4.243zm0-5.758a3 3 0 10-4.243-4.243 3 3 0 004.243 4.243z"
        />
      </svg>
    ),
  },
];

export function WorkspaceShell({
  userEmail,
  userPlan = "free",
}: WorkspaceShellProps) {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<SidebarTabId>("smart-split");
  const [accountPopoverOpen, setAccountPopoverOpen] = useState(false);

  const activeItem =
    MENU_ITEMS.find((item) => item.id === activeTab) ?? MENU_ITEMS[0];

  async function handleLogout() {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push("/login");
    router.refresh();
  }

  return (
    <div className="flex h-screen w-full overflow-hidden bg-zinc-950 font-sans text-zinc-200">
      {/* 1. Sidebar Principal (Esquerda) */}
      <aside className="flex w-64 shrink-0 flex-col border-r border-zinc-800 bg-zinc-950">
        {/* Logo */}
        <div className="flex h-14 items-center gap-2.5 border-b border-zinc-800/60 px-4">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg border border-emerald-500/40 bg-emerald-600/20 text-emerald-500">
            <svg
              className="h-4 w-4"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
            >
              <circle cx="12" cy="12" r="2" />
              <circle cx="6" cy="6" r="1.5" />
              <circle cx="18" cy="6" r="1.5" />
              <circle cx="6" cy="18" r="1.5" />
              <circle cx="18" cy="18" r="1.5" />
            </svg>
          </div>
          <span className="text-sm font-semibold tracking-tight text-zinc-100">
            Impressão 3D
          </span>
        </div>

        {/* Navegação Principal */}
        <nav className="flex flex-1 flex-col gap-1.5 p-3">
          <p className="px-3 pb-1 pt-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
            Ferramentas
          </p>
          {MENU_ITEMS.map((item) => {
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => setActiveTab(item.id)}
                className={`flex w-full items-center gap-3 rounded-lg px-3.5 py-2.5 text-left text-sm transition-colors ${
                  isActive
                    ? "border-l-2 border-emerald-500 bg-emerald-950/30 font-medium text-emerald-500"
                    : "text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-200"
                }`}
              >
                {item.icon}
                <span className="flex-1 leading-snug">{item.label}</span>
                {item.badge && <Badge variant="new">{item.badge}</Badge>}
              </button>
            );
          })}
        </nav>

        {/* Rodapé da Sidebar: Botões 1 (Conta), 2 (Upgrade), 3 (Logout) */}
        <div className="relative border-t border-zinc-800 p-3">
          {accountPopoverOpen && (
            <div className="mb-3 rounded-xl border border-zinc-800 bg-zinc-900 p-3 text-xs shadow-xl">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-zinc-200">Minha Conta</span>
                <Badge variant={userPlan === "pro" ? "pro" : "default"}>
                  {userPlan === "pro" ? "PRO" : "FREE"}
                </Badge>
              </div>
              <p className="mt-1.5 truncate text-zinc-400" title={userEmail}>
                {userEmail}
              </p>
            </div>
          )}

          <div className="grid grid-cols-3 gap-2">
            {/* 1 - CONTA */}
            <IconButton
              title={`Conta (${userEmail})`}
              active={accountPopoverOpen}
              onClick={() => setAccountPopoverOpen((prev) => !prev)}
              className="flex flex-col items-center gap-1 py-2.5"
            >
              <svg
                className="h-4 w-4"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={1.8}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
                />
              </svg>
              <span className="text-[10px] font-medium">Conta</span>
            </IconButton>

            {/* 2 - UPGRADE */}
            <button
              type="button"
              title="Fazer Upgrade para Pro"
              className="flex flex-col items-center justify-center gap-1 rounded-lg border border-amber-500/40 bg-amber-500/15 py-2.5 text-amber-400 transition-colors hover:bg-amber-500 hover:text-zinc-950"
            >
              <svg
                className="h-4 w-4"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={1.8}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z"
                />
              </svg>
              <span className="text-[10px] font-semibold">Upgrade</span>
            </button>

            {/* 3 - LOGOUT */}
            <IconButton
              title="Sair da conta"
              onClick={handleLogout}
              className="flex flex-col items-center gap-1 py-2.5 hover:border-red-500/40 hover:bg-red-950/30 hover:text-red-400"
            >
              <svg
                className="h-4 w-4"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={1.8}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"
                />
              </svg>
              <span className="text-[10px] font-medium">Logout</span>
            </IconButton>
          </div>
        </div>
      </aside>

      {/* 2. Painel de Propriedades (Meio-Esquerda) */}
      <section className="flex w-[320px] shrink-0 flex-col border-r border-zinc-800 bg-zinc-900">
        {/* Cabeçalho do Painel de Propriedades */}
        <div className="flex h-14 items-center justify-between border-b border-zinc-800 px-4">
          <h2 className="text-sm font-semibold text-zinc-200">
            {activeItem.label}
          </h2>
          <Badge variant="beta">Painel</Badge>
        </div>

        {/* Conteúdo rolável do Painel de Propriedades */}
        <div className="flex flex-1 flex-col overflow-y-auto p-4">
          <div className="flex flex-1 flex-col items-center justify-center rounded-xl border-2 border-dashed border-zinc-800 bg-zinc-950/40 p-6 text-center">
            <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full border border-zinc-800 bg-zinc-900 text-emerald-500">
              {activeItem.icon}
            </div>
            <p className="text-sm font-medium text-zinc-300">
              {activeItem.label}
            </p>
            <p className="mt-1 text-xs text-zinc-500">
              As propriedades e controles desta etapa serão exibidos nesta
              coluna.
            </p>
          </div>
        </div>

        {/* Rodapé fixo do Painel de Propriedades */}
        <div className="mt-auto border-t border-zinc-800 p-4">
          <button
            type="button"
            className="flex w-full items-center justify-center gap-2 rounded-xl border border-zinc-700 bg-zinc-800 py-3 text-sm font-medium text-emerald-500 transition-colors hover:bg-zinc-700"
          >
            <span>Ação Principal</span>
          </button>
        </div>
      </section>

      {/* 3. Área Principal (Canvas 3D e Header) */}
      <main className="relative flex flex-1 flex-col overflow-hidden">
        {/* Header Superior da Área Principal */}
        <header className="flex h-14 w-full shrink-0 items-center justify-between border-b border-zinc-800/50 bg-zinc-950 px-6">
          {/* Breadcrumb / Título à esquerda */}
          <div className="flex items-center gap-2.5 text-sm">
            <span className="text-emerald-500">{activeItem.icon}</span>
            <span className="font-semibold text-zinc-200">
              {activeItem.label}
            </span>
          </div>

          {/* Indicadores / Ações à direita */}
          <div className="flex items-center gap-3">
            <span className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-xs text-zinc-400">
              Workspace 3D
            </span>
            <div
              title={userEmail}
              className="flex h-8 w-8 items-center justify-center rounded-full border border-emerald-500/40 bg-emerald-600/20 text-xs font-semibold uppercase text-emerald-400"
            >
              {userEmail ? userEmail.charAt(0) : "U"}
            </div>
          </div>
        </header>

        {/* Área do Canvas 3D Central */}
        <div className="relative flex flex-1 flex-col items-center justify-center bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-zinc-800 to-zinc-950">
          {/* Placeholder do Canvas 3D */}
          <div className="z-0 flex flex-col items-center justify-center text-center">
            <div className="mb-3 flex h-16 w-16 items-center justify-center rounded-2xl border border-zinc-700/60 bg-zinc-900/80 text-emerald-500 shadow-lg">
              <svg
                className="h-8 w-8"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={1.5}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"
                />
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M3.27 6.96L12 12.01l8.73-5.05M12 22.08V12"
                />
              </svg>
            </div>
            <p className="text-sm font-medium text-zinc-300">
              Área Principal — Visualizador 3D
            </p>
            <p className="mt-1 max-w-sm text-xs text-zinc-500">
              O Canvas 3D interativo e a visualização das mesas de trabalho
              ficarão permanentemente visíveis neste espaço.
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}

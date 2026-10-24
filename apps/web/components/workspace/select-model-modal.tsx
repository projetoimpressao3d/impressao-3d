"use client";

import React from "react";
import type { Model } from "@/types/database";

function formatDimensions(model: Model): string | null {
  const {
    bounding_box_x_mm: x,
    bounding_box_y_mm: y,
    bounding_box_z_mm: z,
  } = model;
  if (x == null || y == null || z == null) return null;
  return `${x.toFixed(1)} × ${y.toFixed(1)} × ${z.toFixed(1)} mm`;
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

interface SelectModelModalProps {
  models: Model[];
  onSelectModel: (model: Model) => void;
  onGoToUpload: () => void;
  onClose: () => void;
}

export function SelectModelModal({
  models,
  onSelectModel,
  onGoToUpload,
  onClose,
}: SelectModelModalProps) {
  return (
    <div className="absolute inset-0 z-30 flex items-center justify-center bg-zinc-950/75 p-6 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-2xl border border-zinc-800 bg-zinc-900 p-6 shadow-2xl">
        {/* Cabeçalho */}
        <div className="mb-5 flex items-center justify-between border-b border-zinc-800 pb-4">
          <div>
            <h3 className="text-base font-semibold text-zinc-100">
              Selecione o modelo cadastrado:
            </h3>
            <p className="mt-0.5 text-xs text-zinc-400">
              Escolha um dos modelos enviados para iniciar a Divisão Inteligente.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-zinc-200"
            title="Fechar"
          >
            <svg
              className="h-4 w-4"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>

        {/* Lista de modelos */}
        {models.length === 0 ? (
          <div className="rounded-xl border border-dashed border-zinc-800 bg-zinc-950/40 p-6 text-center">
            <p className="text-sm font-medium text-zinc-300">
              Nenhum modelo cadastrado ainda
            </p>
            <p className="mt-1 text-xs text-zinc-500">
              Envie seu primeiro arquivo 3MF ou STL na aba Modelos para começar.
            </p>
            <button
              type="button"
              onClick={onGoToUpload}
              className="mt-4 inline-flex items-center gap-2 rounded-xl border border-emerald-500/50 bg-emerald-600 px-4 py-2 text-xs font-semibold text-white transition-colors hover:bg-emerald-500"
            >
              Ir para Modelos
            </button>
          </div>
        ) : (
          <div className="max-h-[340px] space-y-2.5 overflow-y-auto pr-1">
            {models.map((model) => {
              const dims = formatDimensions(model);
              return (
                <button
                  key={model.id}
                  type="button"
                  onClick={() => onSelectModel(model)}
                  className="group flex w-full items-center justify-between rounded-xl border border-zinc-800 bg-zinc-950/70 p-3.5 text-left transition-all hover:border-emerald-500/70 hover:bg-emerald-950/20"
                >
                  <div className="min-w-0 flex-1 pr-3">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-semibold text-zinc-100 group-hover:text-emerald-400">
                        {model.name}
                      </span>
                      <span className="shrink-0 rounded border border-zinc-700 bg-zinc-900 px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase text-zinc-300">
                        {model.format}
                      </span>
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-3 text-xs">
                      {dims ? (
                        <span className="font-mono text-emerald-400">
                          {dims}
                        </span>
                      ) : (
                        <span className="text-zinc-500">
                          Dimensões em análise…
                        </span>
                      )}
                      <span
                        className="text-[11px] text-zinc-500"
                        suppressHydrationWarning
                      >
                        Enviado em {formatDate(model.created_at)}
                      </span>
                    </div>
                  </div>

                  <span className="shrink-0 rounded-lg border border-emerald-500/40 bg-emerald-600/20 px-3 py-1.5 text-xs font-semibold text-emerald-400 transition-colors group-hover:bg-emerald-600 group-hover:text-white">
                    Selecionar →
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

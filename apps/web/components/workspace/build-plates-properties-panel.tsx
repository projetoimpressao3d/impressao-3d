"use client";

import React, { useState } from "react";
import type { BuildPlate } from "@/types/database";
import { Badge } from "@/components/ui/badge";

interface BuildPlatesPropertiesPanelProps {
  plates: BuildPlate[];
  selectedPlateId?: string | null;
  onCreateNew: () => void;
  onEditPlate: (plate: BuildPlate) => void;
  onDeletedPlate: () => void;
}

export function BuildPlatesPropertiesPanel({
  plates,
  selectedPlateId,
  onCreateNew,
  onEditPlate,
  onDeletedPlate,
}: BuildPlatesPropertiesPanelProps) {
  const [deletingId, setDeletingId] = useState<string | null>(null);

  async function handleDelete(e: React.MouseEvent, plate: BuildPlate) {
    e.stopPropagation();
    if (
      !confirm(
        `Excluir a mesa "${plate.name}"? Esta ação não pode ser desfeita.`,
      )
    ) {
      return;
    }

    setDeletingId(plate.id);
    try {
      const res = await fetch(`/api/build-plates/${plate.id}`, {
        method: "DELETE",
      });

      if (!res.ok) {
        alert("Erro ao excluir mesa. Tente novamente.");
        setDeletingId(null);
        return;
      }

      setDeletingId(null);
      onDeletedPlate();
    } catch {
      alert("Erro de comunicação ao excluir mesa.");
      setDeletingId(null);
    }
  }

  return (
    <div className="flex flex-1 flex-col overflow-y-auto p-4">
      {/* Botão Grande: Cadastrar nova mesa de trabalho */}
      <button
        type="button"
        onClick={onCreateNew}
        className="group flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-zinc-700 bg-zinc-950/60 p-6 text-center transition-all hover:border-emerald-500/70 hover:bg-emerald-950/20"
      >
        <div className="flex h-20 w-20 items-center justify-center rounded-2xl border border-zinc-700 bg-zinc-900 text-zinc-300 shadow-inner transition-colors group-hover:border-emerald-500/60 group-hover:bg-emerald-600/20 group-hover:text-emerald-400">
          <svg
            className="h-10 w-10"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.8}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M12 4v16m8-8H4"
            />
          </svg>
        </div>
        <span className="mt-3 text-xs font-medium leading-snug text-zinc-200 group-hover:text-emerald-400">
          Cadastrar nova
          <br />
          mesa de trabalho
        </span>
      </button>

      {/* Divisor */}
      <div className="my-5 border-t border-zinc-800" />

      {/* Lista de Mesas Cadastradas */}
      <div className="mb-2.5 flex items-center justify-between">
        <span className="text-xs font-semibold text-zinc-300">
          Mesas cadastradas:
        </span>
        <span className="text-[11px] text-zinc-500">{plates.length}</span>
      </div>

      {plates.length === 0 ? (
        <div className="rounded-xl border border-dashed border-zinc-800 bg-zinc-950/30 p-5 text-center">
          <p className="text-xs font-medium text-zinc-400">
            Nenhuma mesa cadastrada
          </p>
          <p className="mt-1 text-[11px] text-zinc-500">
            Clique no botão &ldquo;+&rdquo; acima para adicionar sua primeira
            impressora.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-2.5">
          {plates.map((plate) => {
            const isSelected = selectedPlateId === plate.id;
            const isDeleting = deletingId === plate.id;

            return (
              <div
                key={plate.id}
                onClick={() => onEditPlate(plate)}
                className={`group cursor-pointer rounded-xl border p-3.5 transition-all ${
                  isSelected
                    ? "border-emerald-500 bg-emerald-950/20"
                    : "border-zinc-800 bg-zinc-950/60 hover:border-zinc-700 hover:bg-zinc-800/50"
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="truncate text-xs font-semibold text-zinc-100">
                        {plate.name}
                      </span>
                      {plate.is_default && (
                        <Badge variant="beta">⭐ Padrão</Badge>
                      )}
                    </div>

                    <p className="mt-1 font-mono text-xs text-emerald-400">
                      {plate.build_volume_x_mm} × {plate.build_volume_y_mm} ×{" "}
                      {plate.build_volume_z_mm} mm
                    </p>
                    <p className="text-[10px] text-zinc-500">
                      Largura × Profundidade × Altura
                    </p>

                    {plate.nozzle_diameter_mm && (
                      <p className="mt-1 text-[11px] text-zinc-400">
                        🔩 Bico: {plate.nozzle_diameter_mm} mm
                      </p>
                    )}
                  </div>

                  {/* Ações: Editar / Excluir */}
                  <div className="flex shrink-0 items-center gap-1">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onEditPlate(plate);
                      }}
                      title="Editar mesa"
                      className="rounded-lg border border-zinc-800 bg-zinc-900 p-1.5 text-zinc-400 transition-colors hover:border-zinc-700 hover:bg-zinc-800 hover:text-zinc-200"
                    >
                      <svg
                        className="h-3.5 w-3.5"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                        strokeWidth={1.8}
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"
                        />
                      </svg>
                    </button>

                    <button
                      type="button"
                      disabled={isDeleting}
                      onClick={(e) => handleDelete(e, plate)}
                      title="Excluir mesa"
                      className="rounded-lg border border-zinc-800 bg-zinc-900 p-1.5 text-zinc-400 transition-colors hover:border-red-500/40 hover:bg-red-950/40 hover:text-red-400 disabled:opacity-50"
                    >
                      <svg
                        className="h-3.5 w-3.5"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                        strokeWidth={1.8}
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                        />
                      </svg>
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

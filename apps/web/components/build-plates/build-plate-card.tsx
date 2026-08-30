"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import type { BuildPlate } from "@/types/database";

interface BuildPlateCardProps {
  plate: BuildPlate;
}

export function BuildPlateCard({ plate }: BuildPlateCardProps) {
  const router = useRouter();
  const [deleting, setDeleting] = useState(false);

  async function handleDelete() {
    if (!confirm(`Excluir a mesa "${plate.name}"? Esta ação não pode ser desfeita.`)) {
      return;
    }

    setDeleting(true);
    const res = await fetch(`/api/build-plates/${plate.id}`, { method: "DELETE" });

    if (!res.ok) {
      alert("Erro ao excluir mesa. Tente novamente.");
      setDeleting(false);
      return;
    }

    router.refresh();
  }

  return (
    <div className="flex items-start justify-between rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-medium text-gray-900">{plate.name}</span>
          {plate.is_default && (
            <span className="rounded-full bg-brand-100 px-2 py-0.5 text-xs font-medium text-brand-700">
              ⭐ Padrão
            </span>
          )}
        </div>

        {/* Dimensões */}
        <p className="mt-1 font-mono text-sm text-gray-600">
          {plate.build_volume_x_mm} × {plate.build_volume_y_mm} × {plate.build_volume_z_mm} mm
        </p>
        <p className="text-xs text-gray-400">
          Largura × Profundidade × Altura
        </p>

        {plate.nozzle_diameter_mm && (
          <p className="mt-1 text-xs text-gray-500">
            🔩 Bico: {plate.nozzle_diameter_mm} mm
          </p>
        )}
      </div>

      {/* Ações */}
      <div className="ml-4 flex shrink-0 items-center gap-2">
        <Link
          href={`/build-plates/${plate.id}/edit`}
          className="rounded-md border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50"
        >
          Editar
        </Link>
        <button
          onClick={handleDelete}
          disabled={deleting}
          className="rounded-md border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {deleting ? "Excluindo…" : "Excluir"}
        </button>
      </div>
    </div>
  );
}

"use client";

import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import type { Model } from "@/types/database";

const STATUS_CONFIG: Record<
  Model["printability_status"],
  { label: string; className: string }
> = {
  pending: { label: "Analisando...", className: "bg-yellow-100 text-yellow-800" },
  ok:      { label: "Pronto",        className: "bg-green-100 text-green-800" },
  warning: { label: "Atencao",       className: "bg-orange-100 text-orange-800" },
  error:   { label: "Erro",          className: "bg-red-100 text-red-800" },
};

const FORMAT_LABEL: Record<string, string> = {
  stl:  "STL",
  "3mf": "3MF",
  obj:  "OBJ",
  gltf: "GLTF",
};

function formatDimensions(model: Model): string | null {
  const { bounding_box_x_mm: x, bounding_box_y_mm: y, bounding_box_z_mm: z } = model;
  if (x == null || y == null || z == null) return null;
  return `${x.toFixed(1)} x ${y.toFixed(1)} x ${z.toFixed(1)} mm`;
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("pt-BR", {
    day: "2-digit", month: "2-digit", year: "numeric",
  });
}

interface ModelCardProps {
  model: Model;
  plan: "free" | "pro";
}

export function ModelCard({ model, plan }: ModelCardProps) {
  const router = useRouter();
  const status = STATUS_CONFIG[model.printability_status];
  const dimensions = formatDimensions(model);
  const canDelete = plan === "pro";

  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  async function handleDelete() {
    if (!confirm(`Excluir "${model.name}"? Esta acao nao pode ser desfeita.`)) return;

    setDeleting(true);
    setDeleteError(null);

    try {
      const res = await fetch(`/api/models/${model.id}`, { method: "DELETE" });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.message ?? "Erro ao excluir modelo.");
      }
      router.refresh();
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Erro desconhecido.");
      setDeleting(false);
    }
  }

  return (
    <div className="flex items-start justify-between rounded-lg border border-gray-200 bg-white p-4 shadow-sm transition-shadow hover:shadow-md">
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex items-center gap-2">
          <span className="truncate font-medium text-gray-900">{model.name}</span>
          <span className="shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-xs font-medium text-gray-600">
            {FORMAT_LABEL[model.format] ?? model.format.toUpperCase()}
          </span>
        </div>

        {dimensions && (
          <p className="text-xs text-gray-500">&#128208; {dimensions}</p>
        )}

        {model.original_filename && model.original_filename !== model.name && (
          <p className="truncate text-xs text-gray-400">{model.original_filename}</p>
        )}

        <p className="text-xs text-gray-400">Enviado em {formatDate(model.created_at)}</p>

        {deleteError && (
          <p className="mt-1 text-xs text-red-600">{deleteError}</p>
        )}
      </div>

      <div className="ml-4 flex shrink-0 flex-col items-end gap-2">
        <span
          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${status.className}`}
        >
          {status.label}
        </span>

        <Link
          href={`/models/${model.id}`}
          className="text-xs font-medium text-brand-600 hover:underline"
        >
          Visualizar
        </Link>

        {/* Botao excluir — pro: ativo | free: bloqueado com explicacao */}
        {canDelete ? (
          <button
            onClick={handleDelete}
            disabled={deleting}
            className="text-xs font-medium text-red-500 hover:text-red-700 hover:underline disabled:opacity-50"
          >
            {deleting ? "Excluindo..." : "Excluir"}
          </button>
        ) : (
          <span
            title="A exclusao de modelos esta disponivel apenas no plano Pro."
            className="cursor-not-allowed text-xs font-medium text-gray-300 select-none"
          >
            &#128274; Excluir
          </span>
        )}
      </div>
    </div>
  );
}
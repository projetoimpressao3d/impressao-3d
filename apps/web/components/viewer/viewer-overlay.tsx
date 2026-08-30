"use client";

import type { BuildPlate } from "@/types/database";
import type { ModelDimensions } from "./model-viewer";

interface ViewerOverlayProps {
  dims: ModelDimensions | null;
  buildPlates: BuildPlate[];
  selectedPlateId: string | null;
  onPlateChange: (id: string | null) => void;
}

type AxisFit = { fits: boolean; model: number; plate: number };

function checkFit(
  dims: ModelDimensions,
  plate: BuildPlate,
): { x: AxisFit; y: AxisFit; z: AxisFit; overall: boolean } {
  const axes = {
    x: { fits: dims.x <= plate.build_volume_x_mm, model: dims.x, plate: plate.build_volume_x_mm },
    y: { fits: dims.y <= plate.build_volume_y_mm, model: dims.y, plate: plate.build_volume_y_mm },
    z: { fits: dims.z <= plate.build_volume_z_mm, model: dims.z, plate: plate.build_volume_z_mm },
  };
  return { ...axes, overall: axes.x.fits && axes.y.fits && axes.z.fits };
}

function AxisRow({ label, fit }: { label: string; fit: AxisFit }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-3 font-bold text-gray-400">{label}</span>
      <span className="font-mono text-white">{fit.model.toFixed(1)}</span>
      <span className="text-gray-500">/</span>
      <span className="font-mono text-gray-400">{fit.plate.toFixed(1)} mm</span>
      <span className={fit.fits ? "text-green-400" : "text-red-400"}>
        {fit.fits ? "✓" : "✗"}
      </span>
    </div>
  );
}

/**
 * Overlay HTML posicionado sobre o canvas com:
 * - Dimensões do modelo (bounding box)
 * - Seletor de mesa de trabalho
 * - Comparação eixo a eixo (modelo vs mesa)
 */
export function ViewerOverlay({
  dims,
  buildPlates,
  selectedPlateId,
  onPlateChange,
}: ViewerOverlayProps) {
  const selectedPlate = buildPlates.find((p) => p.id === selectedPlateId) ?? null;
  const fit = dims && selectedPlate ? checkFit(dims, selectedPlate) : null;

  return (
    <div className="flex items-start gap-3 border-t border-gray-700 bg-gray-900 p-3">
      {/* Dimensões do modelo */}
      <div className="min-w-0 flex-1 rounded-lg bg-gray-800 p-3">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
          Dimensões do modelo
        </p>
        {dims ? (
          <div className="space-y-1">
            <div className="flex items-center gap-2 text-xs">
              <span className="w-3 font-bold text-gray-400">X</span>
              <span className="font-mono text-white">{dims.x.toFixed(1)} mm</span>
              <span className="text-gray-600">(largura)</span>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span className="w-3 font-bold text-gray-400">Y</span>
              <span className="font-mono text-white">{dims.y.toFixed(1)} mm</span>
              <span className="text-gray-600">(profundidade)</span>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span className="w-3 font-bold text-gray-400">Z</span>
              <span className="font-mono text-white">{dims.z.toFixed(1)} mm</span>
              <span className="text-gray-600">(altura)</span>
            </div>
          </div>
        ) : (
          <p className="text-xs text-gray-500">
            Aguardando análise ou carregamento do modelo…
          </p>
        )}
      </div>

      {/* Comparação com a mesa */}
      <div className="min-w-0 flex-1 rounded-lg bg-gray-800 p-3">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
          Mesa de trabalho
        </p>

        {/* Seletor de mesa */}
        {buildPlates.length === 0 ? (
          <a
            href="/build-plates/new"
            className="text-xs text-brand-400 underline hover:text-brand-300"
          >
            + Cadastrar mesa de trabalho
          </a>
        ) : (
          <select
            value={selectedPlateId ?? ""}
            onChange={(e) => onPlateChange(e.target.value || null)}
            className="mb-2 w-full rounded border border-gray-600 bg-gray-700 px-2 py-1 text-xs text-white focus:border-brand-500 focus:outline-none"
          >
            <option value="">— Selecione uma mesa —</option>
            {buildPlates.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
                {p.is_default ? " ⭐" : ""}
                {" "}({p.build_volume_x_mm}×{p.build_volume_y_mm}×{p.build_volume_z_mm} mm)
              </option>
            ))}
          </select>
        )}

        {/* Resultado da comparação */}
        {fit && dims && selectedPlate ? (
          <div className="space-y-1">
            <AxisRow label="X" fit={fit.x} />
            <AxisRow label="Y" fit={fit.y} />
            <AxisRow label="Z" fit={fit.z} />
            <div
              className={`mt-2 rounded px-2 py-1 text-center text-xs font-semibold ${
                fit.overall
                  ? "bg-green-900/50 text-green-300"
                  : "bg-red-900/50 text-red-300"
              }`}
            >
              {fit.overall
                ? "✅ Modelo cabe na mesa"
                : "❌ Modelo não cabe na mesa"}
            </div>
          </div>
        ) : selectedPlate && !dims ? (
          <p className="text-xs text-gray-500">
            Aguardando dimensões do modelo…
          </p>
        ) : null}
      </div>

      {/* Controles de câmera (dica) */}
      <div className="hidden rounded-lg bg-gray-800 p-3 lg:block">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
          Controles
        </p>
        <div className="space-y-1 text-xs text-gray-500">
          <p>🖱️ Botão esquerdo — rotacionar</p>
          <p>🖱️ Botão direito — mover</p>
          <p>🖱️ Scroll — zoom</p>
        </div>
      </div>
    </div>
  );
}

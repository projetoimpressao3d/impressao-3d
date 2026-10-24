"use client";

import React, { useState, useEffect, useCallback } from "react";
import dynamic from "next/dynamic";
import * as THREE from "three";
import type { BuildPlate, Model } from "@/types/database";
import type { ModelDimensions } from "@/components/viewer/model-viewer";
import type { ColorGroup } from "@/components/viewer/threemf-colored-object";

const ViewerScene = dynamic(
  () =>
    import("@/components/viewer/viewer-scene").then((m) => ({
      default: m.ViewerScene,
    })),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full w-full items-center justify-center text-sm text-zinc-400">
        Iniciando visualizador 3D…
      </div>
    ),
  },
);

type AxisFit = { fits: boolean; model: number; plate: number };

function checkFit(
  dims: ModelDimensions,
  plate: BuildPlate,
): { x: AxisFit; y: AxisFit; z: AxisFit; overall: boolean } {
  const axes = {
    x: {
      fits: dims.x <= plate.build_volume_x_mm,
      model: dims.x,
      plate: plate.build_volume_x_mm,
    },
    y: {
      fits: dims.y <= plate.build_volume_y_mm,
      model: dims.y,
      plate: plate.build_volume_y_mm,
    },
    z: {
      fits: dims.z <= plate.build_volume_z_mm,
      model: dims.z,
      plate: plate.build_volume_z_mm,
    },
  };
  return { ...axes, overall: axes.x.fits && axes.y.fits && axes.z.fits };
}

function AxisRow({ label, fit }: { label: string; fit: AxisFit }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-3 font-bold text-zinc-400">{label}</span>
      <span className="font-mono text-zinc-100">{fit.model.toFixed(1)}</span>
      <span className="text-zinc-600">/</span>
      <span className="font-mono text-zinc-400">{fit.plate.toFixed(1)} mm</span>
      <span className={fit.fits ? "text-emerald-400" : "text-red-400"}>
        {fit.fits ? "✓" : "✗"}
      </span>
    </div>
  );
}

interface WorkspaceCanvasProps {
  model: Model | null;
  buildPlates: BuildPlate[];
  selectedPlateId: string | null;
  onPlateChange: (id: string | null) => void;
  onOpenCreatePlate?: () => void;
}

export function WorkspaceCanvas({
  model,
  buildPlates,
  selectedPlateId,
  onPlateChange,
  onOpenCreatePlate,
}: WorkspaceCanvasProps) {
  const [signedUrl, setSignedUrl] = useState<string | null>(null);
  const [urlError, setUrlError] = useState<string | null>(null);
  const [computedDims, setComputedDims] = useState<ModelDimensions | null>(
    null,
  );
  const [colorGroups, setColorGroups] = useState<ColorGroup[]>([]);

  useEffect(() => {
    if (!model) {
      setSignedUrl(null);
      setUrlError(null);
      setComputedDims(null);
      setColorGroups([]);
      return;
    }

    setSignedUrl(null);
    setUrlError(null);
    setComputedDims(null);
    setColorGroups([]);

    fetch(`/api/models/${model.id}/signed-url`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<{ url: string }>;
      })
      .then((data) => setSignedUrl(data.url))
      .catch(() =>
        setUrlError(
          "Não foi possível carregar o arquivo 3D. Tente selecionar o modelo novamente.",
        ),
      );
  }, [model?.id]);

  const handleBboxChange = useCallback((bbox: THREE.Box3) => {
    const size = new THREE.Vector3();
    bbox.getSize(size);
    setComputedDims({
      x: Math.abs(size.x),
      y: Math.abs(size.z), // Three.js Y é altura; Z é profundidade
      z: Math.abs(size.y),
    });
  }, []);

  if (!model) {
    return (
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
          Clique no botão de visualização em um dos seus modelos enviados para
          carregá-lo na mesa 3D.
        </p>
      </div>
    );
  }

  const effectiveDims: ModelDimensions | null =
    model.bounding_box_x_mm != null &&
    model.bounding_box_y_mm != null &&
    model.bounding_box_z_mm != null
      ? {
          x: model.bounding_box_x_mm,
          y: model.bounding_box_y_mm,
          z: model.bounding_box_z_mm,
        }
      : computedDims;

  const selectedPlate =
    buildPlates.find((p) => p.id === selectedPlateId) ?? null;
  const fit =
    effectiveDims && selectedPlate
      ? checkFit(effectiveDims, selectedPlate)
      : null;

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      {/* Cena 3D */}
      <div className="relative flex-1 overflow-hidden">
        {urlError ? (
          <div className="flex h-full items-center justify-center p-6 text-sm text-red-400">
            {urlError}
          </div>
        ) : signedUrl ? (
          <ViewerScene
            url={signedUrl}
            format={model.format as "stl" | "3mf"}
            selectedPlate={selectedPlate}
            onBboxChange={handleBboxChange}
            colorGroups={colorGroups}
            onGroupsParsed={setColorGroups}
          />
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-zinc-400">
            Carregando modelo 3D…
          </div>
        )}
      </div>

      {/* Barra Inferior: Dimensões do Modelo + Mesa de Trabalho + Controles */}
      <div className="flex shrink-0 items-start gap-3 border-t border-zinc-800 bg-zinc-950 p-3">
        {/* Dimensões do modelo */}
        <div className="min-w-0 flex-1 rounded-xl border border-zinc-800 bg-zinc-900 p-3">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-zinc-400">
            Dimensões do modelo
          </p>
          {effectiveDims ? (
            <div className="space-y-1">
              <div className="flex items-center gap-2 text-xs">
                <span className="w-3 font-bold text-zinc-400">X</span>
                <span className="font-mono text-zinc-100">
                  {effectiveDims.x.toFixed(1)} mm
                </span>
                <span className="text-zinc-500">(largura)</span>
              </div>
              <div className="flex items-center gap-2 text-xs">
                <span className="w-3 font-bold text-zinc-400">Y</span>
                <span className="font-mono text-zinc-100">
                  {effectiveDims.y.toFixed(1)} mm
                </span>
                <span className="text-zinc-500">(profundidade)</span>
              </div>
              <div className="flex items-center gap-2 text-xs">
                <span className="w-3 font-bold text-zinc-400">Z</span>
                <span className="font-mono text-zinc-100">
                  {effectiveDims.z.toFixed(1)} mm
                </span>
                <span className="text-zinc-500">(altura)</span>
              </div>
            </div>
          ) : (
            <p className="text-xs text-zinc-500">
              Aguardando análise ou carregamento do modelo…
            </p>
          )}
        </div>

        {/* Comparação com a mesa */}
        <div className="min-w-0 flex-1 rounded-xl border border-zinc-800 bg-zinc-900 p-3">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-zinc-400">
            Mesa de trabalho
          </p>

          {buildPlates.length === 0 ? (
            <button
              type="button"
              onClick={onOpenCreatePlate}
              className="text-xs font-medium text-emerald-400 underline hover:text-emerald-300"
            >
              + Cadastrar mesa de trabalho
            </button>
          ) : (
            <select
              value={selectedPlateId ?? ""}
              onChange={(e) => onPlateChange(e.target.value || null)}
              className="mb-2 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-2.5 py-1.5 text-xs text-zinc-100 focus:border-emerald-500 focus:outline-none"
            >
              <option value="">— Selecione uma mesa —</option>
              {buildPlates.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                  {p.is_default ? " ⭐" : ""} ({p.build_volume_x_mm}×
                  {p.build_volume_y_mm}×{p.build_volume_z_mm} mm)
                </option>
              ))}
            </select>
          )}

          {fit && effectiveDims && selectedPlate ? (
            <div className="space-y-1">
              <AxisRow label="X" fit={fit.x} />
              <AxisRow label="Y" fit={fit.y} />
              <AxisRow label="Z" fit={fit.z} />
              <div
                className={`mt-2 rounded-lg border px-2 py-1 text-center text-xs font-semibold ${
                  fit.overall
                    ? "border-emerald-500/40 bg-emerald-950/40 text-emerald-400"
                    : "border-red-500/40 bg-red-950/40 text-red-400"
                }`}
              >
                {fit.overall
                  ? "✅ Modelo cabe na mesa"
                  : "❌ Modelo não cabe na mesa"}
              </div>
            </div>
          ) : selectedPlate && !effectiveDims ? (
            <p className="text-xs text-zinc-500">
              Aguardando dimensões do modelo…
            </p>
          ) : null}
        </div>

        {/* Controles de câmera */}
        <div className="hidden rounded-xl border border-zinc-800 bg-zinc-900 p-3 xl:block">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-zinc-400">
            Controles
          </p>
          <div className="space-y-1 text-xs text-zinc-400">
            <p>🖱️ Botão esquerdo — rotacionar</p>
            <p>🖱️ Botão direito — mover</p>
            <p>🖱️ Scroll — zoom</p>
          </div>
        </div>
      </div>
    </div>
  );
}

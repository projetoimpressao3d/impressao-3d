"use client";

import { useState } from "react";
import type { BuildPlate } from "@/types/database";

export interface FilamentInfo {
  index: number;
  extruder_number: number;
  color_hex: string;
  face_count: number;
  face_percentage: number;
}

export interface PlateOutput {
  plate_number: number;
  extruder_number: number;
  color_hex: string;
  storage_path: string;
  download_url: string;
  fits_in_plate: boolean;
  extents_mm: number[];
}

interface ColorSplitPanelProps {
  modelId: string;
  modelFormat: string;
  buildPlates: BuildPlate[];
  selectedPlateId: string | null;
  onPlateChange: (id: string) => void;
  hasSubscription: boolean;
  onShowPreview?: () => void;
  colorPreviewMode?: boolean;
}


function ColorSwatch({ hex }: { hex: string }) {
  return (
    <span
      className="inline-block h-4 w-4 rounded-sm border border-gray-600 shadow-sm"
      style={{ backgroundColor: hex }}
    />
  );
}

function fmm(v: number) {
  return v.toFixed(1);
}

export function ColorSplitPanel({
  modelId,
  modelFormat,
  buildPlates,
  selectedPlateId,
  onPlateChange,
  hasSubscription,
  onShowPreview,
  colorPreviewMode = false,
}: ColorSplitPanelProps) {

  const [colorInfo, setColorInfo] = useState<{
    is_painted: boolean;
    total_faces: number;
    filaments: FilamentInfo[];
    method?: string;
  } | null>(null);

  const [plates, setPlates] = useState<PlateOutput[]>([]);
  const [loading, setLoading] = useState(false);
  const [splitting, setSplitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  // Opcao de posicionamento: true = encosta na base; false = posicao original
  const [snapToFloor, setSnapToFloor] = useState(true);

  const selectedPlate = buildPlates.find((p) => p.id === selectedPlateId);
  const is3mf = modelFormat === "3mf";

  // Etapa 1: Detectar cores
  const handleDetectColors = async () => {
    setLoading(true);
    setError(null);
    setColorInfo(null);
    setDone(false);
    setPlates([]);

    try {
      const res = await fetch(`/api/color-split/${modelId}/info`);
      if (!res.ok) {
        const err = (await res.json()) as { detail?: string };
        throw new Error(err.detail ?? `HTTP ${res.status}`);
      }
      const data = (await res.json()) as {
        is_painted: boolean;
        total_faces: number;
        filaments: FilamentInfo[];
      };
      setColorInfo(data);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  };

  // Etapa 2: Separar pecas por cor
  const handleSplitByColor = async () => {
    if (!selectedPlateId) return;
    setSplitting(true);
    setError(null);

    try {
      const res = await fetch(`/api/color-split/${modelId}/split`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ build_plate_id: selectedPlateId, snap_to_floor: snapToFloor }),
      });
      if (!res.ok) {
        const err = (await res.json()) as { detail?: string };
        throw new Error(err.detail ?? `HTTP ${res.status}`);
      }
      const data = (await res.json()) as {
        plates: PlateOutput[];
        total_pieces: number;
        oversized_count: number;
      };
      setPlates(data.plates);
      setDone(true);

    } catch (err) {
      setError(String(err));
    } finally {
      setSplitting(false);
    }
  };

  // Modelo nao e 3mf
  if (!is3mf) {
    return (
      <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4">
        <p className="text-sm font-semibold text-amber-800">Formato nao suportado</p>
        <p className="mt-1 text-xs text-amber-700">
          A separacao por cor requer um arquivo <strong>.3mf</strong> pintado no Bambu Studio,
          OrcaSlicer ou PrusaSlicer. Faca o upload de um arquivo .3mf pintado.
        </p>
      </div>
    );
  }

  return (
    <div className="mt-4 space-y-4">
      {/* Selecao de mesa */}
      <div>
        <label className="block text-xs font-medium text-gray-400 mb-1">
          Mesa de impressao
        </label>
        <select
          className="w-full rounded-lg bg-gray-800 border border-gray-700 px-3 py-2 text-sm text-white"
          value={selectedPlateId ?? ""}
          onChange={(e) => onPlateChange(e.target.value)}
        >
          {buildPlates.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name} ({p.build_volume_x_mm}x{p.build_volume_y_mm}x{p.build_volume_z_mm}mm)
            </option>
          ))}
        </select>
      </div>

      {/* Etapa 1: Detectar cores */}
      {!colorInfo && !done && (
        <button
          className="w-full rounded-xl bg-indigo-600 px-4 py-3 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-60 transition-colors"
          onClick={handleDetectColors}
          disabled={loading}
        >
          {loading ? (
            <span className="flex items-center justify-center gap-2">
              <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
              Detectando cores...
            </span>
          ) : (
            "🎨 Detectar Cores do Modelo"
          )}
        </button>
      )}

      {/* Resultado da detecao */}
      {colorInfo && !done && (
        <div className="space-y-3">
          {colorInfo.is_painted ? (
            <>
              <div className="rounded-xl border border-emerald-700 bg-emerald-950/40 p-3">
                <p className="text-xs font-semibold text-emerald-400 mb-1">
                  ✅ {colorInfo.filaments.length} cores detectadas
                </p>
                {colorInfo.method === "multi_object" && (
                  <p className="text-[10px] text-emerald-600 mb-2">
                    🧩 Peças fisicamente separadas (sem AMS necessário)
                  </p>
                )}
                <div className="space-y-1.5">
                  {colorInfo.filaments.map((f) => (
                    <div key={f.index} className="flex items-center gap-2 text-xs text-gray-300">
                      <ColorSwatch hex={f.color_hex} />
                      <span className="font-mono text-gray-400">Ext {f.extruder_number}</span>
                      <span>{f.face_count.toLocaleString()} faces</span>
                      <span className="ml-auto text-gray-500">{f.face_percentage}%</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Toggle: posicionamento das pecas no download */}
              <div className="rounded-xl border border-gray-700 bg-gray-800/60 p-3">
                <p className="text-xs font-semibold text-gray-300 mb-2">📐 Posicao no download</p>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => setSnapToFloor(true)}
                    className={`flex-1 rounded-lg px-3 py-2 text-xs font-medium transition-colors ${
                      snapToFloor
                        ? "bg-emerald-700 text-white"
                        : "bg-gray-700 text-gray-400 hover:bg-gray-600"
                    }`}
                  >
                    📦 Na base (Z=0)
                  </button>
                  <button
                    type="button"
                    onClick={() => setSnapToFloor(false)}
                    className={`flex-1 rounded-lg px-3 py-2 text-xs font-medium transition-colors ${
                      !snapToFloor
                        ? "bg-indigo-700 text-white"
                        : "bg-gray-700 text-gray-400 hover:bg-gray-600"
                    }`}
                  >
                    🌐 Posicao original
                  </button>
                </div>
                <p className="mt-1.5 text-[10px] text-gray-500">
                  {snapToFloor
                    ? "Cada peca sera encostada na base da mesa para impressao direta."
                    : "Mantem a posicao original do modelo (pode flutuar acima da mesa)."}
                </p>
              </div>

              <button
                className="w-full rounded-xl bg-emerald-600 px-4 py-3 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-60 transition-colors"
                onClick={handleSplitByColor}
                disabled={splitting || !selectedPlateId}
              >
                {splitting ? (
                  <span className="flex items-center justify-center gap-2">
                    <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                    </svg>
                    Separando pecas...
                  </span>
                ) : (
                  "✂️ Separar Pecas por Cor"
                )}
              </button>


              <button
                className="w-full rounded-lg px-4 py-2 text-xs text-gray-400 hover:text-gray-300 transition-colors"
                onClick={() => setColorInfo(null)}
              >
                Cancelar
              </button>
            </>
          ) : (
            <div className="rounded-xl border border-amber-700 bg-amber-950/40 p-3">
              <p className="text-xs font-semibold text-amber-400">⚠️ Modelo sem cores identificadas</p>
              <p className="mt-1 text-xs text-amber-300">
                Este arquivo .3mf nao possui cores de filamento pintadas nem pecas separadas por extruder.
                Use o Bambu Studio para pintar o modelo ou organize as pecas por extruder.
              </p>
            </div>
          )}
        </div>
      )}


      {/* Resultado: lista de downloads por peca */}
      {done && plates.length > 0 && (
        <div className="space-y-3">
          <p className="text-xs font-semibold text-emerald-400">
            ✅ {plates.length} {plates.length === 1 ? "peca separada" : "pecas separadas"} com sucesso!
          </p>

          {/* Botão de visualização 3D das peças nas mesas */}
          {onShowPreview && (
            <button
              className={`w-full rounded-xl px-4 py-2.5 text-sm font-semibold transition-colors ${
                colorPreviewMode
                  ? "bg-emerald-700 text-white hover:bg-emerald-600"
                  : "bg-gray-700 text-gray-200 hover:bg-gray-600"
              }`}
              onClick={onShowPreview}
            >
              {colorPreviewMode ? "👁 Ocultar visualização 3D" : "👁 Ver peças nas mesas (3D)"}
            </button>
          )}

          <div className="space-y-2">
            {plates.map((plate) => {
              const sizeStr = plate.extents_mm.map(fmm).join("x") + "mm";
              return (
                <div
                  key={`${plate.plate_number}-${plate.extruder_number}`}
                  className="flex items-center gap-3 rounded-lg border border-gray-700 bg-gray-800/60 p-3"
                >
                  <ColorSwatch hex={plate.color_hex} />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-semibold text-white">
                      Extruder {plate.extruder_number}
                    </p>
                    <p className="text-[10px] text-gray-400 font-mono">{sizeStr}</p>
                    {!plate.fits_in_plate && (
                      <p className="text-[10px] text-amber-400">
                        ⚠️ Maior que a mesa ({selectedPlate?.name})
                      </p>
                    )}
                  </div>
                  {hasSubscription ? (
                    <a
                      href={plate.download_url}
                      download
                      className="flex-shrink-0 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500 transition-colors"
                    >
                      Download
                    </a>
                  ) : (
                    <span className="flex-shrink-0 rounded-lg bg-gray-700 px-3 py-1.5 text-xs font-semibold text-gray-400">
                      🔒 Pro
                    </span>
                  )}
                </div>
              );
            })}
          </div>

          <button
            className="w-full rounded-lg border border-gray-700 px-4 py-2 text-xs text-gray-400 hover:text-gray-300 transition-colors"
            onClick={() => {
              setDone(false);
              setColorInfo(null);
              setPlates([]);
            }}
          >
            Nova separacao
          </button>
        </div>
      )}

      {/* Erro */}
      {error && (
        <div className="rounded-xl border border-red-700 bg-red-950/40 p-3">
          <p className="text-xs font-semibold text-red-400">Erro</p>
          <p className="mt-1 text-xs text-red-300">{error}</p>
        </div>
      )}
    </div>
  );
}
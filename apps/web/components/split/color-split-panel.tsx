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
  label?: string | null;
  is_subdivided?: boolean;
}

export interface ColorSplitResult {
  model_id: string;
  plates: PlateOutput[];
  total_pieces: number;
  oversized_count: number;
  unified_download_url?: string | null;
  unified_file_name?: string | null;
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
  onSplitOversizedPiece?: (plate: PlateOutput) => void;
  // After any split/subdivide completes, propagate to the viewer for 3D preview
  onSplitCompleted?: (result: ColorSplitResult) => void;
}


function ColorSwatch({ hex }: { hex: string }) {
  return (
    <span
      className="inline-block h-4 w-4 rounded-sm border border-gray-600 shadow-sm flex-shrink-0"
      style={{ backgroundColor: hex }}
    />
  );
}

function fmm(v: number) {
  return v.toFixed(1);
}

type SubdivideMode = "character" | "general";

interface SubdivideConfig {
  plate: PlateOutput;
  mode: SubdivideMode;
  characterTemplate: string;
  generalGranularity: string;
  sensitivity: number;
  generateConnectors: boolean;
  connectorPinShape: "hex" | "triangle" | "cylinder";
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
  onSplitOversizedPiece,
  onSplitCompleted,
}: ColorSplitPanelProps) {

  const [colorInfo, setColorInfo] = useState<{
    is_painted: boolean;
    total_faces: number;
    filaments: FilamentInfo[];
    method?: string;
  } | null>(null);

  const [splitResult, setSplitResult] = useState<ColorSplitResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [splitting, setSplitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [snapToFloor, setSnapToFloor] = useState(true);

  // Subdivide inline flow
  const [subdividingPlate, setSubdividingPlate] = useState<PlateOutput | null>(null);
  const [subdivideConfig, setSubdivideConfig] = useState<Omit<SubdivideConfig, "plate">>({
    mode: "character",
    characterTemplate: "creature",
    generalGranularity: "auto",
    sensitivity: 5,
    generateConnectors: true,
    connectorPinShape: "hex",
  });
  const [isSubdividing, setIsSubdividing] = useState(false);

  const selectedPlate = buildPlates.find((p) => p.id === selectedPlateId);
  const is3mf = modelFormat === "3mf";

  // ── Etapa 1: Detectar cores ──────────────────────────────────────────────
  const handleDetectColors = async () => {
    setLoading(true);
    setError(null);
    setColorInfo(null);
    setDone(false);
    setSplitResult(null);
    setSubdividingPlate(null);

    try {
      const res = await fetch(`/api/color-split/${modelId}/info`);
      if (!res.ok) {
        const err = (await res.json()) as { detail?: string };
        if (res.status === 503) {
          throw new Error(
            "O serviço de processamento não está disponível no momento. " +
            "O backend Python precisa ser configurado para usar esta funcionalidade.",
          );
        }
        throw new Error(err.detail ?? `Erro HTTP ${res.status}`);
      }
      const data = (await res.json()) as {
        is_painted: boolean;
        total_faces: number;
        filaments: FilamentInfo[];
      };
      setColorInfo(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  // ── Etapa 2: Separar peças por cor ──────────────────────────────────────
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
      const data = (await res.json()) as ColorSplitResult;
      setSplitResult(data);
      setDone(true);
      onSplitCompleted?.(data);
    } catch (err) {
      setError(String(err));
    } finally {
      setSplitting(false);
    }
  };

  // ── Etapa 3: Subdividir peça oversized (inline) ──────────────────────────
  const handleSubdividePiece = async () => {
    if (!subdividingPlate || !selectedPlateId) return;
    setIsSubdividing(true);
    setError(null);

    try {
      const res = await fetch(`/api/color-split/${modelId}/subdivide`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          build_plate_id: selectedPlateId,
          extruder_number: subdividingPlate.extruder_number,
          mode: subdivideConfig.mode,
          character_template: subdivideConfig.characterTemplate,
          general_granularity: subdivideConfig.generalGranularity,
          structural_sensitivity: subdivideConfig.sensitivity / 100,
          generate_connectors: subdivideConfig.generateConnectors,
          connector_pin_shape: subdivideConfig.connectorPinShape,
          connector_tolerance_mm: 0.2,
          snap_to_floor: snapToFloor,
        }),
      });

      if (!res.ok) {
        const err = (await res.json()) as { detail?: string };
        throw new Error(err.detail ?? `HTTP ${res.status}`);
      }

      const data = (await res.json()) as ColorSplitResult;
      setSplitResult(data);
      setSubdividingPlate(null);
      onSplitCompleted?.(data);
    } catch (err) {
      setError(String(err));
    } finally {
      setIsSubdividing(false);
    }
  };

  // ── Guard: apenas .3mf ──────────────────────────────────────────────────
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

  // ── Painel inline de configuração de subdivisão ──────────────────────────
  if (subdividingPlate) {
    const modeLabels: Record<SubdivideMode, string> = {
      character: "🦴 Divisão Anatômica (Character Split)",
      general: "📐 Divisão Geral Auto-Fit (BSP)",
    };

    return (
      <div className="mt-4 space-y-4">
        <div className="rounded-xl border border-amber-700 bg-amber-950/30 px-4 py-3">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold text-amber-300">
                ✂️ Fatiando Extruder {subdividingPlate.extruder_number}
              </p>
              <p className="text-[11px] text-amber-500 mt-0.5">
                {subdividingPlate.extents_mm.map(fmm).join(" × ")} mm
                {" · "}⚠️ Não cabe na mesa {selectedPlate?.name ?? ""}
              </p>
            </div>
            <ColorSwatch hex={subdividingPlate.color_hex} />
          </div>
          <p className="mt-2 text-[11px] text-amber-400">
            Todas as cores do modelo serão preservadas. Somente a peça selecionada será fatiada.
            Ao final, você poderá baixar um arquivo .3mf unificado com todas as divisões.
          </p>
        </div>

        {/* Seleção do modo */}
        <div className="rounded-xl border border-gray-700 bg-gray-800/60 p-3 space-y-2">
          <p className="text-xs font-semibold text-gray-300">Modo de divisão</p>
          <div className="grid grid-cols-2 gap-2">
            {(["character", "general"] as SubdivideMode[]).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setSubdivideConfig((c) => ({ ...c, mode: m }))}
                className={`rounded-lg px-3 py-2.5 text-xs font-medium text-left transition-colors ${
                  subdivideConfig.mode === m
                    ? m === "character"
                      ? "bg-emerald-700 text-white"
                      : "bg-violet-700 text-white"
                    : "bg-gray-700 text-gray-400 hover:bg-gray-600"
                }`}
              >
                {modeLabels[m]}
              </button>
            ))}
          </div>
          <p className="text-[10px] text-gray-500">
            {subdivideConfig.mode === "character"
              ? "Detecta membros anatômicos (asas, cauda, cabeça) e secciona nos gargalos articulares."
              : "Decomposição BSP recursiva para formas arbitrárias, garantindo que cada peça caiba na mesa."}
          </p>
        </div>

        {/* Config: Character Split */}
        {subdivideConfig.mode === "character" && (
          <div className="rounded-xl border border-emerald-800/50 bg-emerald-950/20 p-3 space-y-2">
            <div>
              <label className="block text-[10px] font-semibold uppercase tracking-wider text-emerald-400 mb-1">
                Template Anatômico
              </label>
              <select
                value={subdivideConfig.characterTemplate}
                onChange={(e) => setSubdivideConfig((c) => ({ ...c, characterTemplate: e.target.value }))}
                className="w-full rounded-lg border border-emerald-700 bg-gray-800 px-2 py-1.5 text-xs text-white focus:border-emerald-500 focus:outline-none"
              >
                <option value="creature">🐉 Criatura Alada (Asas, Cauda, Cabeça)</option>
                <option value="a">👤 Template A: 6 partes (Cabeça + Membros)</option>
                <option value="b">👤 Template B: 5 partes</option>
                <option value="d">👤 Template D: 4 partes com Cabeça</option>
                <option value="f">🥋 Template F: 2 partes (Cintura)</option>
                <option value="auto">✨ Detecção Automática</option>
              </select>
            </div>
            <div>
              <div className="flex items-center justify-between text-[11px] text-emerald-400">
                <span>Sensibilidade de apêndices:</span>
                <span className="font-mono font-semibold">{subdivideConfig.sensitivity}%</span>
              </div>
              <input
                type="range"
                min={1}
                max={25}
                value={subdivideConfig.sensitivity}
                onChange={(e) => setSubdivideConfig((c) => ({ ...c, sensitivity: Number(e.target.value) }))}
                className="w-full accent-emerald-500 mt-1"
              />
            </div>
          </div>
        )}

        {/* Config: General Split */}
        {subdivideConfig.mode === "general" && (
          <div className="rounded-xl border border-violet-800/50 bg-violet-950/20 p-3 space-y-2">
            <label className="block text-[10px] font-semibold uppercase tracking-wider text-violet-400 mb-1">
              Granularidade
            </label>
            <select
              value={subdivideConfig.generalGranularity}
              onChange={(e) => setSubdivideConfig((c) => ({ ...c, generalGranularity: e.target.value }))}
              className="w-full rounded-lg border border-violet-700 bg-gray-800 px-2 py-1.5 text-xs text-white focus:border-violet-500 focus:outline-none"
            >
              <option value="auto">🎯 Auto-Fit (Garante encaixe na mesa)</option>
              <option value="low">⚡ Baixa (Mínimo de cortes)</option>
              <option value="medium">⚖️ Média (Margem de segurança 10%)</option>
              <option value="high">🧩 Alta (Peças menores modulares)</option>
            </select>
          </div>
        )}

        {/* Config: Conectores */}
        <div className="rounded-xl border border-indigo-800/40 bg-indigo-950/20 p-3 space-y-2">
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={subdivideConfig.generateConnectors}
              onChange={(e) => setSubdivideConfig((c) => ({ ...c, generateConnectors: e.target.checked }))}
              className="h-4 w-4 rounded border-indigo-700 text-indigo-500"
            />
            <span className="text-xs font-semibold text-indigo-300">
              🧩 Conectores Mecânicos Macho/Fêmea (0.2mm folga)
            </span>
          </label>
          {subdivideConfig.generateConnectors && (
            <div className="flex items-center gap-2 pl-6">
              <span className="text-[11px] text-indigo-400">Formato:</span>
              <select
                value={subdivideConfig.connectorPinShape}
                onChange={(e) => setSubdivideConfig((c) => ({ ...c, connectorPinShape: e.target.value as "hex" | "triangle" | "cylinder" }))}
                className="rounded border border-indigo-700 bg-gray-800 px-2 py-1 text-xs text-white focus:outline-none"
              >
                <option value="hex">Hexagonal (Anti-rotação)</option>
                <option value="triangle">Triangular</option>
                <option value="cylinder">Cilíndrico</option>
              </select>
            </div>
          )}
        </div>

        {error && (
          <div className="rounded-xl border border-red-700 bg-red-950/40 p-3">
            <p className="text-xs text-red-300">{error}</p>
          </div>
        )}

        <div className="flex gap-2">
          <button
            className="flex-1 rounded-xl bg-amber-600 px-4 py-3 text-sm font-semibold text-white hover:bg-amber-500 disabled:opacity-60 transition-colors"
            onClick={handleSubdividePiece}
            disabled={isSubdividing || !selectedPlateId}
          >
            {isSubdividing ? (
              <span className="flex items-center justify-center gap-2">
                <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                </svg>
                Processando... pode levar 30-90s
              </span>
            ) : (
              "✂️ Fatiar e Gerar Arquivo Completo"
            )}
          </button>
          <button
            className="rounded-xl border border-gray-600 px-4 py-3 text-sm text-gray-400 hover:text-gray-200 transition-colors"
            onClick={() => { setSubdividingPlate(null); setError(null); }}
            disabled={isSubdividing}
          >
            Cancelar
          </button>
        </div>
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


      {/* Resultado: lista de peças com downloads */}
      {done && splitResult && splitResult.plates.length > 0 && (
        <div className="space-y-3">
          {/* Header e status */}
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold text-emerald-400">
              ✅ {splitResult.total_pieces} {splitResult.total_pieces === 1 ? "peça separada" : "peças separadas"}
            </p>
            {splitResult.oversized_count > 0 && (
              <span className="rounded bg-amber-900/60 px-2 py-0.5 text-[10px] text-amber-300">
                ⚠️ {splitResult.oversized_count} excede a mesa
              </span>
            )}
          </div>

          {/* Botão de visualização 3D */}
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

          {/* Download unificado (DESTAQUE) */}
          {splitResult.unified_download_url && (
            <a
              href={splitResult.unified_download_url}
              download={splitResult.unified_file_name ?? "modelo_completo.3mf"}
              className="flex items-center justify-between w-full rounded-xl border border-emerald-600 bg-emerald-900/40 px-4 py-3 transition-colors hover:bg-emerald-900/70 group"
            >
              <div>
                <p className="text-xs font-semibold text-emerald-300 group-hover:text-emerald-200">
                  ⬇ Baixar Arquivo Completo (.3mf)
                </p>
                <p className="text-[10px] text-emerald-500 mt-0.5">
                  Todas as {splitResult.total_pieces} peças e cores em um único arquivo
                </p>
              </div>
              <span className="flex-shrink-0 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm">
                .3mf
              </span>
            </a>
          )}

          {/* Lista individual por peça/cor */}
          <div className="space-y-2">
            {splitResult.plates.map((plate, idx) => {
              const sizeStr = plate.extents_mm.map(fmm).join("×") + "mm";
              const label = plate.label ?? `Extruder ${plate.extruder_number}`;
              return (
                <div
                  key={`${plate.plate_number}-${plate.extruder_number}-${idx}`}
                  className={`flex items-center gap-3 rounded-lg border p-3 ${
                    plate.is_subdivided
                      ? "border-amber-700/50 bg-amber-950/20"
                      : "border-gray-700 bg-gray-800/60"
                  }`}
                >
                  <ColorSwatch hex={plate.color_hex} />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-semibold text-white truncate">
                      {plate.is_subdivided && <span className="text-amber-400 mr-1">✂</span>}
                      {label}
                    </p>
                    <p className="text-[10px] text-gray-400 font-mono">{sizeStr}</p>
                    {!plate.fits_in_plate && (
                      <div className="mt-1 flex flex-col items-start gap-1">
                        <p className="text-[10px] text-amber-400">
                          ⚠️ Maior que a mesa ({selectedPlate?.name})
                        </p>
                        {hasSubscription && (
                          <button
                            type="button"
                            onClick={() => {
                              setSubdividingPlate(plate);
                              setError(null);
                              onSplitOversizedPiece?.(plate);
                            }}
                            className="inline-flex items-center gap-1 rounded bg-amber-600/90 px-2 py-0.5 text-[10px] font-medium text-white transition hover:bg-amber-500 shadow-sm"
                          >
                            ✂️ Fatiar Peça para Caber
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                  {hasSubscription ? (
                    <a
                      href={plate.download_url}
                      download
                      className="flex-shrink-0 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500 transition-colors"
                    >
                      ⬇
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
              setSplitResult(null);
              setSubdividingPlate(null);
              setError(null);
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
"use client";

import { useState, useEffect, useRef, useCallback } from "react";
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
  part_labels?: string[];
  has_connectors?: boolean;
}

export interface ColorSplitResult {
  model_id: string;
  plates: PlateOutput[];
  total_pieces: number;
  oversized_count: number;
  unified_download_url?: string | null;
  unified_file_name?: string | null;
  filaments?: FilamentInfo[];
  generate_connectors?: boolean;
  interface_pins?: number;
  subdivided_colors?: number[];
  method?: string;
}

interface ColorSplitPanelProps {
  modelId: string;
  modelFormat: string;
  buildPlates: BuildPlate[];
  selectedPlateId: string | null;
  onPlateChange: (id: string) => void;
  hasSubscription: boolean;
  generateConnectors?: boolean;
  autoStart?: boolean;
  onShowPreview?: () => void;
  colorPreviewMode?: boolean;
  onSplitCompleted?: (result: ColorSplitResult) => void;
  onReset?: () => void;
  selectedColorPlateIdx?: number | "all";
  onSelectColorPlateIdx?: (idx: number | "all") => void;
  onSwitchToLinearMode?: () => void;
}

function ColorSwatch({ hex }: { hex: string }) {
  return (
    <span
      className="inline-block h-4 w-4 rounded-sm border border-zinc-700 shadow-sm flex-shrink-0"
      style={{ backgroundColor: hex }}
    />
  );
}

function fmm(v: number) {
  return v.toFixed(1);
}

async function safeErrorMessage(res: Response): Promise<string> {
  try {
    const ct = res.headers.get("content-type") ?? "";
    if (ct.includes("application/json")) {
      const j = (await res.json()) as {
        detail?: string;
        error?: string;
        message?: string;
      };
      return j.detail ?? j.error ?? j.message ?? `HTTP ${res.status}`;
    }
    const text = await res.text();
    return text.trim() || `HTTP ${res.status}`;
  } catch {
    return `HTTP ${res.status}`;
  }
}

export function ColorSplitPanel({
  modelId,
  modelFormat,
  buildPlates,
  selectedPlateId,
  hasSubscription: _hasSubscription,
  generateConnectors = false,
  autoStart = true,
  onShowPreview,
  colorPreviewMode = false,
  onSplitCompleted,
  onReset,
  selectedColorPlateIdx,
  onSelectColorPlateIdx,
}: ColorSplitPanelProps) {
  const [splitResult, setSplitResult] = useState<ColorSplitResult | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [stage, setStage] = useState("Iniciando processo...");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const selectedPlate = buildPlates.find((p) => p.id === selectedPlateId);
  const is3mf = modelFormat === "3mf";
  const startedRef = useRef(false);

  const handleStartAutoSplit = useCallback(async () => {
    if (!selectedPlateId) {
      setError("Selecione uma mesa de trabalho antes de iniciar.");
      return;
    }
    setIsProcessing(true);
    setError(null);
    setProgress(5);
    setStage("Iniciando separação automática...");
    setDone(false);
    setSplitResult(null);

    try {
      const res = await fetch(`/api/color-split/${modelId}/auto-split`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          build_plate_id: selectedPlateId,
          generate_connectors: generateConnectors,
          material: "PLA",
          connector_pin_shape: "hex",
          cap_method: "earcut",
        }),
      });

      if (!res.ok) {
        throw new Error(await safeErrorMessage(res));
      }

      const data = (await res.json()) as { task_id: string };
      if (!data.task_id) {
        throw new Error("Não foi retornado identificador de tarefa do servidor.");
      }

      const taskId = data.task_id;
      let isCompleted = false;
      let attempts = 0;
      const maxAttempts = 120; // até 4 minutos

      while (!isCompleted && attempts < maxAttempts) {
        attempts++;
        await new Promise((resolve) => setTimeout(resolve, 2000));

        const pollRes = await fetch(`/api/color-split/tasks/${taskId}`);
        if (!pollRes.ok) {
          throw new Error("Falha ao consultar status do processamento.");
        }

        const pollData = (await pollRes.json()) as {
          status: "processing" | "completed" | "failed";
          progress?: number;
          stage?: string;
          error?: string;
          result?: ColorSplitResult;
        };

        if (pollData.progress !== undefined) {
          setProgress(pollData.progress);
        }
        if (pollData.stage) {
          setStage(pollData.stage);
        }

        if (pollData.status === "completed" && pollData.result) {
          isCompleted = true;
          setSplitResult(pollData.result);
          setDone(true);
          setIsProcessing(false);
          setProgress(100);
          onSplitCompleted?.(pollData.result);
          break;
        } else if (pollData.status === "failed") {
          throw new Error(pollData.error || "O processamento da malha falhou.");
        }
      }

      if (!isCompleted) {
        throw new Error("O processamento excedeu o tempo limite. Tente novamente.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setIsProcessing(false);
    }
  }, [modelId, selectedPlateId, generateConnectors, onSplitCompleted]);

  // Auto-inicia ao carregar caso autoStart=true e ainda não tenha rodado
  useEffect(() => {
    if (autoStart && !startedRef.current && !done && !isProcessing && selectedPlateId) {
      startedRef.current = true;
      void handleStartAutoSplit();
    }
  }, [autoStart, done, isProcessing, selectedPlateId, handleStartAutoSplit]);

  if (!is3mf) {
    return (
      <div className="rounded-xl border border-amber-500/40 bg-amber-950/30 p-4">
        <p className="text-xs font-semibold text-amber-300">
          Formato não suportado
        </p>
        <p className="mt-1 text-[11px] text-amber-400">
          A separação por cores requer um arquivo <strong>.3mf</strong> pintado
          (Bambu Studio, OrcaSlicer, PrusaSlicer).
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* 1. Estado em Processamento com barra de progresso */}
      {isProcessing && (
        <div className="rounded-xl border border-emerald-500/40 bg-emerald-950/20 p-4 text-center">
          <div className="flex items-center justify-center gap-2.5 text-xs font-bold text-emerald-300">
            <svg
              className="h-4 w-4 animate-spin text-emerald-400"
              viewBox="0 0 24 24"
              fill="none"
            >
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8v8H4z"
              />
            </svg>
            <span>
              {generateConnectors
                ? "Separação por Cores + Pinos de Encaixe"
                : "Separação por Cores"}
            </span>
          </div>

          <p className="mt-2 text-xs font-medium text-emerald-400">{stage}</p>

          {/* Barra de progresso */}
          <div className="mt-3.5 h-2 w-full overflow-hidden rounded-full bg-zinc-800">
            <div
              className="h-full rounded-full bg-gradient-to-r from-emerald-600 to-emerald-400 transition-all duration-300"
              style={{ width: `${Math.max(5, progress)}%` }}
            />
          </div>
          <p className="mt-1.5 font-mono text-[11px] text-zinc-400">
            {progress}% concluído
          </p>

          <p className="mt-3 text-[10px] text-zinc-400">
            O processo está identificando as cores, subdividindo as peças maiores
            que a mesa {selectedPlate?.name ? `(${selectedPlate.name})` : ""} e
            gerando arquivos 3MF prontos para impressão.
          </p>
        </div>
      )}

      {/* 2. Botão Manual caso ainda não tenha iniciado ou resetado */}
      {!isProcessing && !done && (
        <div className="space-y-2.5">
          <button
            type="button"
            onClick={() => void handleStartAutoSplit()}
            disabled={!selectedPlateId}
            className="w-full rounded-xl bg-emerald-600 px-4 py-3 text-xs font-bold text-white shadow-md transition-colors hover:bg-emerald-500 disabled:opacity-50"
          >
            {generateConnectors
              ? "▶ Iniciar Separação por Cores + Pinos"
              : "▶ Iniciar Separação por Cores"}
          </button>
        </div>
      )}

      {/* 3. Resultado: lista de peças e botões de download */}
      {done && splitResult && (
        <div className="space-y-3">
          {/* Header de Resumo */}
          <div className="rounded-xl border border-emerald-500/30 bg-emerald-950/30 p-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-emerald-300">
                ✅ {splitResult.total_pieces}{" "}
                {splitResult.total_pieces === 1
                  ? "peça gerada"
                  : "peças geradas"}
              </span>
              <span className="rounded bg-emerald-900/60 px-2 py-0.5 text-[10px] font-semibold text-emerald-300">
                {splitResult.plates.length}{" "}
                {splitResult.plates.length === 1 ? "mesa" : "mesas"}
              </span>
            </div>

            <div className="mt-2 flex flex-wrap gap-1.5">
              {generateConnectors && (
                <span className="rounded border border-indigo-500/40 bg-indigo-950/60 px-2 py-0.5 text-[10px] font-medium text-indigo-300">
                  🧩 Pinos de encaixe automáticos
                </span>
              )}
              {splitResult.subdivided_colors &&
                splitResult.subdivided_colors.length > 0 && (
                  <span className="rounded border border-amber-500/40 bg-amber-950/60 px-2 py-0.5 text-[10px] font-medium text-amber-300">
                    ✂️ Peças adaptadas à mesa
                  </span>
                )}
            </div>
          </div>

          {/* Botão de alternar visualização 3D nas mesas */}
          {onShowPreview && (
            <button
              type="button"
              className={`w-full rounded-xl px-4 py-2 text-xs font-semibold transition-colors ${
                colorPreviewMode
                  ? "border border-emerald-500/50 bg-emerald-600 text-white"
                  : "border border-zinc-700 bg-zinc-800 text-zinc-300 hover:bg-zinc-700 hover:text-white"
              }`}
              onClick={onShowPreview}
            >
              {colorPreviewMode
                ? "👁 Ocultar visualização 3D"
                : "👁 Ver peças nas mesas (3D)"}
            </button>
          )}

          {/* Download unificado (DESTAQUE) */}
          {splitResult.unified_download_url && (
            <a
              href={splitResult.unified_download_url}
              download={splitResult.unified_file_name ?? "modelo_completo.3mf"}
              className="group flex w-full items-center justify-between rounded-xl border border-emerald-500/60 bg-emerald-950/40 px-4 py-3 shadow-md transition-colors hover:bg-emerald-900/50"
            >
              <div className="min-w-0 pr-2">
                <p className="text-xs font-bold text-emerald-300 group-hover:text-emerald-200">
                  ⬇ Baixar Arquivo Completo (.3mf)
                </p>
                <p className="truncate text-[10px] text-emerald-400/80">
                  Todas as cores e peças prontas para impressão
                </p>
              </div>
              <span className="shrink-0 rounded-lg bg-emerald-600 px-2.5 py-1 text-xs font-bold text-white shadow-sm">
                .3mf
              </span>
            </a>
          )}

          {/* Lista individual por mesa/cor */}
          <div className="space-y-2">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-zinc-400">
              Mesas de Impressão Geradas:
            </p>
            {splitResult.plates.map((plate, idx) => {
              const sizeStr = plate.extents_mm.map(fmm).join(" × ") + " mm";
              const label = plate.label ?? `Cor ${plate.extruder_number}`;
              const isSelected = selectedColorPlateIdx === idx;

              return (
                <div
                  key={`${plate.plate_number}-${plate.extruder_number}-${idx}`}
                  onClick={() => onSelectColorPlateIdx?.(idx)}
                  className={`flex cursor-pointer items-center gap-2.5 rounded-lg border p-2.5 transition-all ${
                    isSelected
                      ? "border-emerald-500 bg-emerald-950/40 ring-1 ring-emerald-500"
                      : "border-zinc-800 bg-zinc-950/70 hover:border-zinc-700 hover:bg-zinc-800/50"
                  }`}
                >
                  <ColorSwatch hex={plate.color_hex} />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1">
                      <p className="truncate text-xs font-semibold text-zinc-200">
                        {label}
                      </p>
                      {plate.is_subdivided && (
                        <span className="rounded bg-amber-950/60 px-1 py-0.2 text-[9px] font-semibold text-amber-400">
                          ✂ Dividida
                        </span>
                      )}
                      {plate.has_connectors && (
                        <span className="rounded bg-indigo-950/60 px-1 py-0.2 text-[9px] font-semibold text-indigo-400">
                          🧩 Pinos
                        </span>
                      )}
                    </div>
                    <p className="font-mono text-[10px] text-zinc-400">
                      {sizeStr}
                    </p>
                  </div>

                  <div className="flex shrink-0 items-center gap-1">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onSelectColorPlateIdx?.(idx);
                      }}
                      className={`rounded px-2 py-1 text-[11px] font-medium transition-colors ${
                        isSelected
                          ? "bg-emerald-600 text-white"
                          : "bg-zinc-800 text-zinc-300 hover:bg-zinc-700 hover:text-white"
                      }`}
                      title="Exibir no visualizador 3D"
                    >
                      👁 Ver
                    </button>
                    <a
                      href={plate.download_url}
                      download
                      onClick={(e) => e.stopPropagation()}
                      className="rounded bg-emerald-600 px-2 py-1 text-[11px] font-bold text-white transition-colors hover:bg-emerald-500"
                      title="Baixar .3mf desta mesa"
                    >
                      ⬇
                    </a>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Botão de Nova Separação */}
          <button
            type="button"
            className="w-full rounded-xl border border-zinc-800 py-2.5 text-xs text-zinc-400 transition-colors hover:border-zinc-700 hover:bg-zinc-800/40 hover:text-zinc-200"
            onClick={() => {
              setDone(false);
              setSplitResult(null);
              setError(null);
              startedRef.current = false;
              onReset?.();
            }}
          >
            🔄 Nova separação / Escolher outra opção
          </button>
        </div>
      )}

      {/* 4. Erro */}
      {error && (
        <div className="rounded-xl border border-red-500/40 bg-red-950/30 p-3">
          <p className="text-xs font-semibold text-red-400">Erro no processamento</p>
          <p className="mt-1 text-xs text-red-300">{error}</p>
          <button
            type="button"
            onClick={() => void handleStartAutoSplit()}
            className="mt-2.5 rounded-lg bg-red-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-red-500"
          >
            Tentar novamente
          </button>
        </div>
      )}
    </div>
  );
}

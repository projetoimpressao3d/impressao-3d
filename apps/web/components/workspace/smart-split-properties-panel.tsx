"use client";

import React from "react";
import type {
  BuildPlate,
  CutPlaneData,
  ExecutedPiece,
  Model,
  PieceBboxStatus,
} from "@/types/database";
import {
  ColorSplitPanel,
  type ColorSplitResult,
} from "@/components/split/color-split-panel";
import { SplitPanel } from "@/components/split/split-panel";
import { PieceDownload } from "@/components/split/piece-download";

function formatDimensions(model: Model): string | null {
  const {
    bounding_box_x_mm: x,
    bounding_box_y_mm: y,
    bounding_box_z_mm: z,
  } = model;
  if (x == null || y == null || z == null) return null;
  return `${x.toFixed(1)} × ${y.toFixed(1)} × ${z.toFixed(1)} mm`;
}

export type SmartSplitOption = "colors" | "linear" | null;

interface SmartSplitPropertiesPanelProps {
  selectedModel: Model | null;
  onOpenSelectModelModal: () => void;
  selectedOption: SmartSplitOption;
  onSelectOption: (option: SmartSplitOption) => void;
  buildPlates: BuildPlate[];
  selectedPlateId: string | null;
  onPlateChange: (id: string) => void;
  hasSubscription: boolean;

  // Props para ColorSplitPanel
  hasColorGroups: boolean;
  colorPreviewMode: boolean;
  onToggleColorPreview: () => void;
  selectedColorPlateIdx: number | "all";
  onSelectColorPlateIdx: (idx: number | "all") => void;
  onColorSplitCompleted: (result: ColorSplitResult) => void;
  onColorSplitReset: () => void;

  // Props para SplitPanel (Corte Linear)
  sessionId: string | null;
  splitMode:
    | "idle"
    | "loading"
    | "planning"
    | "suggesting"
    | "separating"
    | "executing"
    | "done"
    | "error";
  splitError: string | null;
  cutPlanes: CutPlaneData[];
  selectedPlaneId: string | null;
  transformMode: "translate" | "rotate";
  pieceBboxes: PieceBboxStatus[];
  activeView: "editor" | "preview";
  onViewChange: (view: "editor" | "preview") => void;
  separateFeedback: string | null;
  onStartSplit: () => void;
  onAutoSuggest: () => void;
  onSeparateParts: (sensitivity: number, template: string) => void;
  onGeneralSplit: (granularity: string) => void;
  onAddPlane: () => void;
  onRemovePlane: (id: string) => void;
  onSelectPlane: (id: string | null) => void;
  onSetTransformMode: (mode: "translate" | "rotate") => void;
  onExecute: () => void;
  onCancel: () => void;
  generateConnectors: boolean;
  onToggleConnectors: (enabled: boolean) => void;
  connectorPinShape: "hex" | "triangle" | "cylinder";
  onConnectorPinShapeChange: (shape: "hex" | "triangle" | "cylinder") => void;
  executedPieces: ExecutedPiece[];
}

export function SmartSplitPropertiesPanel({
  selectedModel,
  onOpenSelectModelModal,
  selectedOption,
  onSelectOption,
  buildPlates,
  selectedPlateId,
  onPlateChange,
  hasSubscription,
  hasColorGroups,
  colorPreviewMode,
  onToggleColorPreview,
  selectedColorPlateIdx,
  onSelectColorPlateIdx,
  onColorSplitCompleted,
  onColorSplitReset,
  sessionId,
  splitMode,
  splitError,
  cutPlanes,
  selectedPlaneId,
  transformMode,
  pieceBboxes,
  activeView,
  onViewChange,
  separateFeedback,
  onStartSplit,
  onAutoSuggest,
  onSeparateParts,
  onGeneralSplit,
  onAddPlane,
  onRemovePlane,
  onSelectPlane,
  onSetTransformMode,
  onExecute,
  onCancel,
  generateConnectors,
  onToggleConnectors,
  connectorPinShape,
  onConnectorPinShapeChange,
  executedPieces,
}: SmartSplitPropertiesPanelProps) {
  if (!selectedModel) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center p-4 text-center">
        <div className="w-full rounded-xl border-2 border-dashed border-zinc-800 bg-zinc-950/50 p-6">
          <p className="text-sm font-medium text-zinc-300">
            Nenhum modelo selecionado
          </p>
          <p className="mt-1 text-xs text-zinc-500">
            Selecione um dos seus modelos enviados para configurar a divisão.
          </p>
          <button
            type="button"
            onClick={onOpenSelectModelModal}
            className="mt-4 w-full rounded-xl border border-emerald-500/50 bg-emerald-600 py-2.5 text-xs font-semibold text-white transition-colors hover:bg-emerald-500"
          >
            Selecionar modelo cadastrado
          </button>
        </div>
      </div>
    );
  }

  const dims = formatDimensions(selectedModel);
  const is3mf = selectedModel.format === "3mf";

  return (
    <div className="flex flex-1 flex-col overflow-y-auto p-4">
      {/* 1. Card: Modelo Selecionado */}
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-400">
          Modelo Selecionado:
        </span>
        <button
          type="button"
          onClick={onOpenSelectModelModal}
          className="text-[11px] font-medium text-emerald-400 hover:text-emerald-300 hover:underline"
        >
          Trocar
        </button>
      </div>

      <div className="rounded-xl border border-emerald-500/40 bg-zinc-950/70 p-3.5">
        <div className="flex items-center justify-between gap-2">
          <span
            className="truncate text-xs font-semibold text-zinc-100"
            title={selectedModel.name}
          >
            {selectedModel.name}
          </span>
          <span className="shrink-0 rounded border border-zinc-700 bg-zinc-900 px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase text-zinc-300">
            {selectedModel.format}
          </span>
        </div>
        {dims && (
          <p className="mt-1 font-mono text-xs text-emerald-400">{dims}</p>
        )}
      </div>

      {/* Divisor */}
      <div className="my-5 border-t border-zinc-800" />

      {/* 2. Escolha como deseja dividir as peças */}
      <p className="mb-3 text-center text-xs font-semibold uppercase tracking-wider text-zinc-300">
        Escolha como deseja dividir as peças:
      </p>

      <div className="flex flex-col gap-2.5">
        {/* OPÇÃO 1: Divisão Inteligente por Cores */}
        <button
          type="button"
          onClick={() => onSelectOption("colors")}
          className={`group rounded-xl border p-3.5 text-left transition-all ${
            selectedOption === "colors"
              ? "border-emerald-500 bg-emerald-950/30 shadow-md ring-1 ring-emerald-500/40"
              : "border-zinc-800 bg-zinc-950/60 hover:border-zinc-700 hover:bg-zinc-800/50"
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-xs font-bold text-emerald-400">
              🎨 Separar por Cores
            </span>
            <span className="rounded border border-emerald-500/30 bg-emerald-950/60 px-2 py-0.5 text-[10px] font-medium text-emerald-300">
              1 Bico / Sem AMS
            </span>
          </div>
          <p className="mt-1 text-[11px] leading-snug text-zinc-400">
            Separa cada cor do modelo 3MF em mesas individuais e subdivide peças
            grandes com pinos de encaixe.
          </p>
        </button>

        {/* OPÇÃO 2: Corte Linear / Fatiar Modelo Completo */}
        <button
          type="button"
          onClick={() => onSelectOption("linear")}
          className={`group rounded-xl border p-3.5 text-left transition-all ${
            selectedOption === "linear"
              ? "border-emerald-500 bg-emerald-950/30 shadow-md ring-1 ring-emerald-500/40"
              : "border-zinc-800 bg-zinc-950/60 hover:border-zinc-700 hover:bg-zinc-800/50"
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-xs font-bold text-zinc-100 group-hover:text-emerald-400">
              ✂️ Corte Linear Completo
            </span>
            <span className="rounded border border-zinc-700 bg-zinc-900 px-2 py-0.5 text-[10px] font-medium text-zinc-300">
              {is3mf ? "Multicor / Geral" : "STL / Geral"}
            </span>
          </div>
          <p className="mt-1 text-[11px] leading-snug text-zinc-400">
            Divide o modelo inteiro com planos de corte interativos, gargalos
            naturais ou separação estrutural.
          </p>
        </button>
      </div>

      {/* 3. Conteúdo da opção escolhida */}
      {selectedOption === "colors" && (
        <div className="mt-4 border-t border-zinc-800 pt-2">
          <ColorSplitPanel
            modelId={selectedModel.id}
            modelFormat={selectedModel.format}
            buildPlates={buildPlates}
            selectedPlateId={selectedPlateId}
            onPlateChange={onPlateChange}
            hasSubscription={hasSubscription}
            onShowPreview={hasColorGroups ? onToggleColorPreview : undefined}
            colorPreviewMode={colorPreviewMode}
            selectedColorPlateIdx={selectedColorPlateIdx}
            onSelectColorPlateIdx={onSelectColorPlateIdx}
            onSplitCompleted={onColorSplitCompleted}
            onReset={onColorSplitReset}
            onSwitchToLinearMode={() => onSelectOption("linear")}
          />
        </div>
      )}

      {selectedOption === "linear" && (
        <div className="mt-4 border-t border-zinc-800 pt-2">
          {splitMode === "done" && executedPieces.length > 0 ? (
            <PieceDownload pieces={executedPieces} onClose={onCancel} />
          ) : (
            <SplitPanel
              sessionId={sessionId}
              splitMode={splitMode}
              splitError={splitError}
              cutPlanes={cutPlanes}
              selectedPlaneId={selectedPlaneId}
              transformMode={transformMode}
              pieceBboxes={pieceBboxes}
              buildPlates={buildPlates}
              selectedPlateId={selectedPlateId}
              hasSubscription={hasSubscription}
              activeView={activeView}
              onViewChange={onViewChange}
              separateFeedback={separateFeedback}
              onStartSplit={onStartSplit}
              onAutoSuggest={onAutoSuggest}
              onSeparateParts={onSeparateParts}
              onGeneralSplit={onGeneralSplit}
              onAddPlane={onAddPlane}
              onRemovePlane={onRemovePlane}
              onSelectPlane={onSelectPlane}
              onSetTransformMode={onSetTransformMode}
              onExecute={onExecute}
              onCancel={onCancel}
              onPlateChange={onPlateChange}
              generateConnectors={generateConnectors}
              onToggleConnectors={onToggleConnectors}
              connectorPinShape={connectorPinShape}
              onConnectorPinShapeChange={onConnectorPinShapeChange}
            />
          )}
        </div>
      )}
    </div>
  );
}

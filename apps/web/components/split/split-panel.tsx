"use client";

import type { BuildPlate, CutPlaneData, PieceBboxStatus, ExecutedPiece } from "@/types/database";

interface SplitPanelProps {
  // Sessão
  sessionId: string | null;
  splitMode: "idle" | "loading" | "planning" | "executing" | "done" | "error";
  splitError: string | null;

  // Planos de corte
  cutPlanes: CutPlaneData[];
  selectedPlaneId: string | null;
  transformMode: "translate" | "rotate";

  // Status das peças
  pieceBboxes: PieceBboxStatus[];

  // Mesa de trabalho
  buildPlates: BuildPlate[];
  selectedPlateId: string | null;

  // Assinatura
  hasSubscription: boolean;

  // Callbacks
  onStartSplit: () => void;
  onAddPlane: () => void;
  onRemovePlane: (id: string) => void;
  onSelectPlane: (id: string | null) => void;
  onSetTransformMode: (mode: "translate" | "rotate") => void;
  onExecute: () => void;
  onCancel: () => void;
  onPlateChange: (id: string) => void;
}

/** Formata dimensões em mm com 1 casa decimal. */
function fmm(v: number): string {
  return v.toFixed(1);
}

/**
 * Painel de controle do editor de cortes (fora do canvas 3D).
 * Mostra planos, status das peças e botões de ação.
 */
export function SplitPanel({
  sessionId,
  splitMode,
  splitError,
  cutPlanes,
  selectedPlaneId,
  transformMode,
  pieceBboxes,
  buildPlates,
  selectedPlateId,
  hasSubscription,
  onStartSplit,
  onAddPlane,
  onRemovePlane,
  onSelectPlane,
  onSetTransformMode,
  onExecute,
  onCancel,
  onPlateChange,
}: SplitPanelProps) {
  const selectedPlate = buildPlates.find((p) => p.id === selectedPlateId);

  // ── Estado: idle ─────────────────────────────────────────────────────────
  if (splitMode === "idle") {
    return (
      <div className="mt-4 flex items-center justify-between rounded-xl border border-gray-200 bg-white p-4">
        <div>
          <p className="text-sm font-medium text-gray-800">
            ✂️ Dividir modelo em peças
          </p>
          <p className="mt-0.5 text-xs text-gray-500">
            Selecione uma mesa de trabalho e clique para iniciar o planejamento
            dos cortes.
          </p>
        </div>
        <button
          onClick={onStartSplit}
          disabled={!selectedPlateId || buildPlates.length === 0}
          className="ml-4 shrink-0 rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Dividir modelo
        </button>
      </div>
    );
  }

  // ── Estado: loading ───────────────────────────────────────────────────────
  if (splitMode === "loading") {
    return (
      <div className="mt-4 rounded-xl border border-violet-100 bg-violet-50 p-4">
        <div className="flex items-center gap-3">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-violet-600 border-t-transparent" />
          <p className="text-sm font-medium text-violet-800">
            Analisando geometria do modelo…
          </p>
        </div>
        <div className="mt-3 space-y-1.5 pl-8">
          <p className="flex items-center gap-1.5 text-xs text-violet-700">
            <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-violet-400" />
            Baixando malha do modelo
          </p>
          <p className="flex items-center gap-1.5 text-xs text-violet-700">
            <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-violet-400 [animation-delay:0.3s]" />
            Varrendo 9 direções em busca de gargalos naturais
          </p>
          <p className="flex items-center gap-1.5 text-xs text-violet-700">
            <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-violet-400 [animation-delay:0.6s]" />
            Selecionando cortes mínimos necessários
          </p>
        </div>
        <p className="mt-3 text-xs text-violet-500">
          Pode levar 10–40 s dependendo do tamanho do modelo.
        </p>
      </div>
    );
  }

  // ── Estado: executing ─────────────────────────────────────────────────────
  if (splitMode === "executing") {
    return (
      <div className="mt-4 rounded-xl border border-violet-100 bg-violet-50 p-4">
        <div className="flex items-center gap-3">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-violet-600 border-t-transparent" />
          <p className="text-sm font-medium text-violet-800">
            Executando corte booleano…
          </p>
        </div>
        <p className="mt-2 text-xs text-violet-600">
          O corte com manifold3d pode levar de alguns segundos a 1-2 minutos
          dependendo da complexidade do modelo. Não feche esta janela.
        </p>
      </div>
    );
  }

  // ── Estado: error ─────────────────────────────────────────────────────────
  if (splitMode === "error") {
    return (
      <div className="mt-4 rounded-xl border border-red-200 bg-red-50 p-4">
        <p className="text-sm font-semibold text-red-700">Erro</p>
        <p className="mt-1 text-sm text-red-600">
          {splitError ?? "Ocorreu um erro inesperado."}
        </p>
        {splitError?.includes("Assinatura") && (
          <div className="mt-3 rounded-lg border border-red-200 bg-white p-3 text-xs text-gray-700">
            <p className="font-medium">🔒 Funcionalidade exclusiva para assinantes</p>
            <p className="mt-1">
              A simulação visual do corte é gratuita para todos. Para executar
              o corte real e baixar as peças, é necessária uma assinatura ativa.
            </p>
          </div>
        )}
        <button
          onClick={onCancel}
          className="mt-3 rounded-lg border border-red-200 bg-white px-3 py-1.5 text-xs text-red-600 hover:bg-red-50"
        >
          Voltar ao visualizador
        </button>
      </div>
    );
  }

  // ── Estado: planning ─────────────────────────────────────────────────────
  if (splitMode === "planning") {
    const allFit =
      pieceBboxes.length > 0 && pieceBboxes.every((p) => p.fits);
    const someNoFit = pieceBboxes.some((p) => !p.fits);

    const naturalCount = cutPlanes.filter(
      (p) => p.source === "suggested_natural",
    ).length;
    const gridCount = cutPlanes.filter(
      (p) => p.source === "suggested_grid_fallback",
    ).length;

    return (
      <div className="mt-4 space-y-3">
        {/* Cabeçalho com botões de modo */}
        <div className="flex items-center justify-between rounded-xl border border-gray-200 bg-white p-3">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-gray-800">
              ✂️ Editor de cortes
            </span>
            {selectedPlate && (
              <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-500">
                Mesa: {selectedPlate.name} (
                {selectedPlate.build_volume_x_mm}×
                {selectedPlate.build_volume_y_mm}×
                {selectedPlate.build_volume_z_mm} mm)
              </span>
            )}
          </div>
          <button
            onClick={onCancel}
            className="text-xs text-gray-400 hover:text-gray-600"
          >
            Cancelar
          </button>
        </div>

        {/* Banner de sugestão automática */}
        {cutPlanes.length > 0 && (naturalCount > 0 || gridCount > 0) && (
          <div className="rounded-xl border border-violet-100 bg-violet-50 px-4 py-3">
            <p className="text-xs font-medium text-violet-800">
              🤖 Sugestão automática gerada
            </p>
            <div className="mt-1.5 flex flex-wrap gap-3">
              {naturalCount > 0 && (
                <span className="flex items-center gap-1 text-xs text-violet-700">
                  <span className="inline-block h-2 w-2 rounded-full bg-violet-400" />
                  {naturalCount} gargalo{naturalCount > 1 ? "s" : ""} natural{naturalCount > 1 ? "is" : ""} detectado{naturalCount > 1 ? "s" : ""}
                </span>
              )}
              {gridCount > 0 && (
                <span className="flex items-center gap-1 text-xs text-amber-700">
                  <span className="inline-block h-2 w-2 rounded-full bg-amber-500" />
                  {gridCount} divisão{gridCount > 1 ? "ões" : ""} em grade (sem gargalo natural)
                </span>
              )}
            </div>
            <p className="mt-1.5 text-xs text-violet-500">
              Você pode mover, girar ou remover qualquer plano antes de executar.
            </p>
          </div>
        )}

        {/* Controles do plano selecionado */}
        {selectedPlaneId && (
          <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
            <span className="text-xs font-medium text-amber-700">
              Plano selecionado (laranja):
            </span>
            <button
              onClick={() => onSetTransformMode("translate")}
              className={`rounded px-2 py-1 text-xs font-medium ${
                transformMode === "translate"
                  ? "bg-amber-500 text-white"
                  : "border border-amber-300 text-amber-700 hover:bg-amber-100"
              }`}
            >
              Mover
            </button>
            <button
              onClick={() => onSetTransformMode("rotate")}
              className={`rounded px-2 py-1 text-xs font-medium ${
                transformMode === "rotate"
                  ? "bg-amber-500 text-white"
                  : "border border-amber-300 text-amber-700 hover:bg-amber-100"
              }`}
            >
              Girar
            </button>
            <button
              onClick={() => {
                onRemovePlane(selectedPlaneId);
                onSelectPlane(null);
              }}
              className="ml-auto rounded px-2 py-1 text-xs text-red-600 hover:bg-red-50"
            >
              Remover
            </button>
          </div>
        )}

        {/* Lista de planos */}
        <div className="rounded-xl border border-gray-200 bg-white">
          <div className="flex items-center justify-between border-b border-gray-100 px-3 py-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">
              Planos de corte ({cutPlanes.length})
            </span>
            <button
              onClick={onAddPlane}
              className="rounded-lg bg-violet-50 px-2.5 py-1 text-xs font-medium text-violet-700 hover:bg-violet-100"
            >
              + Adicionar plano
            </button>
          </div>

          {/* Legenda de cores */}
          <div className="flex flex-wrap items-center gap-3 border-b border-gray-50 bg-gray-50 px-3 py-2">
            <span className="text-xs font-medium text-gray-400">Legenda:</span>
            <span className="flex items-center gap-1 text-xs text-gray-500">
              <span className="inline-block h-2 w-2 rounded-full bg-violet-400" />
              Gargalo natural
            </span>
            <span className="flex items-center gap-1 text-xs text-gray-500">
              <span className="inline-block h-2 w-2 rounded-full bg-amber-500" />
              Divisão em grade
            </span>
            <span className="flex items-center gap-1 text-xs text-gray-500">
              <span className="inline-block h-2 w-2 rounded-full bg-gray-400" />
              Manual
            </span>
          </div>

          {cutPlanes.length === 0 ? (
            <p className="px-3 py-4 text-center text-xs text-gray-400">
              Nenhum plano de corte. Clique em &quot;+ Adicionar plano&quot; para começar.
            </p>
          ) : (
            <ul className="divide-y divide-gray-50">
              {cutPlanes.map((plane, idx) => (
                <li
                  key={plane.id}
                  onClick={() =>
                    onSelectPlane(
                      selectedPlaneId === plane.id ? null : plane.id,
                    )
                  }
                  className={`cursor-pointer px-3 py-2.5 transition hover:bg-gray-50 ${
                    selectedPlaneId === plane.id ? "bg-amber-50" : ""
                  }`}
                >
                  {/* Linha principal: ponto + nome + badge */}
                  <div className="flex items-center gap-2">
                    <span
                      className={`h-2 w-2 shrink-0 rounded-full ${
                        selectedPlaneId === plane.id
                          ? "bg-amber-400"
                          : plane.source === "suggested_natural"
                            ? "bg-violet-400"
                            : plane.source === "suggested_grid_fallback"
                              ? "bg-amber-500"
                              : "bg-gray-400"
                      }`}
                    />
                    <span className="text-sm text-gray-700">
                      Plano {idx + 1}
                    </span>

                    {/* Badge por tipo de sugestão */}
                    {plane.source === "suggested_natural" && (
                      <span className="rounded-full bg-violet-100 px-2 py-0.5 text-[10px] font-medium text-violet-700">
                        🔬 Gargalo natural
                      </span>
                    )}
                    {plane.source === "suggested_grid_fallback" && (
                      <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-700">
                        📐 Divisão em grade
                      </span>
                    )}
                    {plane.source === "manual" && (
                      <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-medium text-gray-500">
                        ✏️ Manual
                      </span>
                    )}
                  </div>

                  {/* Linha secundária: label + posição */}
                  <div className="mt-0.5 flex items-center gap-2 pl-4">
                    {plane.label && (
                      <span className="text-xs text-gray-400">{plane.label}</span>
                    )}
                    <span className="ml-auto text-xs text-gray-400">
                      pos ({fmm(plane.px)}, {fmm(plane.py)}, {fmm(plane.pz)}) mm
                    </span>
                  </div>
                </li>

              ))}
            </ul>
          )}
        </div>

        {/* Status das peças resultantes */}
        {pieceBboxes.length > 0 && (
          <div className="rounded-xl border border-gray-200 bg-white">
            <div className="border-b border-gray-100 px-3 py-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                Peças resultantes ({pieceBboxes.length})
              </span>
              {allFit && (
                <span className="ml-2 text-xs text-green-600">
                  ✅ Todas cabem na mesa
                </span>
              )}
              {someNoFit && (
                <span className="ml-2 text-xs text-red-600">
                  ❌ Algumas não cabem
                </span>
              )}
            </div>
            <ul className="divide-y divide-gray-50">
              {pieceBboxes.map((p) => (
                <li
                  key={p.pieceIndex}
                  className="flex items-center gap-2 px-3 py-2 text-sm"
                >
                  <span
                    className={`text-base ${p.fits ? "text-green-500" : "text-red-500"}`}
                  >
                    {p.fits ? "✅" : "❌"}
                  </span>
                  <span className="text-gray-700">Peça {p.pieceIndex + 1}</span>
                  {p.bbox ? (
                    <span className="ml-auto font-mono text-xs text-gray-500">
                      {fmm(p.bbox.x)} × {fmm(p.bbox.y)} × {fmm(p.bbox.z)} mm
                    </span>
                  ) : (
                    <span className="ml-auto text-xs text-gray-400">
                      (mover planos para calcular)
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Botão de confirmação */}
        <div className="flex items-center gap-3">
          <button
            onClick={onCancel}
            className="rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
          >
            Cancelar
          </button>

          {hasSubscription ? (
            <button
              onClick={onExecute}
              disabled={cutPlanes.length === 0}
              className="flex-1 rounded-lg bg-violet-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              ✂️ Executar corte
            </button>
          ) : (
            <div className="flex-1 rounded-lg border border-dashed border-violet-200 bg-violet-50 px-4 py-2 text-center text-sm text-violet-600">
              🔒 Assinatura necessária para executar o corte
            </div>
          )}
        </div>
      </div>
    );
  }

  return null;
}

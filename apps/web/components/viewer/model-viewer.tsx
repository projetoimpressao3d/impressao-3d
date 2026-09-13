"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import dynamic from "next/dynamic";
import * as THREE from "three";
import type {
  BuildPlate,
  CutPlaneData,
  ExecutedPiece,
  Model,
  PieceBboxStatus,
  PlanSessionResponse,
  SuggestResponse,
  StatusPollingResponse,
} from "@/types/database";
import { ViewerOverlay } from "./viewer-overlay";
import { SplitPanel } from "@/components/split/split-panel";
import { PieceDownload } from "@/components/split/piece-download";
import { ColorSplitPanel } from "@/components/split/color-split-panel";

// Dynamic import com ssr: false — Three.js NÃO pode rodar no servidor
const ViewerScene = dynamic(
  () => import("./viewer-scene").then((m) => ({ default: m.ViewerScene })),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full items-center justify-center bg-gray-900 text-sm text-gray-400">
        Iniciando visualizador 3D…
      </div>
    ),
  },
);

export interface ModelDimensions {
  x: number;
  y: number;
  z: number;
}

type SplitMode =
  | "idle"
  | "loading"
  | "planning"
  | "suggesting"   // análise automática de gargalos em andamento
  | "separating"   // separação estrutural por esqueleto (polling)
  | "executing"
  | "done"
  | "error";

interface ModelViewerProps {
  model: Model;
  buildPlates: BuildPlate[];
  hasSubscription?: boolean;
}

/** Gera um quaternion a partir do vetor normal de um plano sugerido. */
function quaternionFromNormal(normal: number[]): {
  qx: number;
  qy: number;
  qz: number;
  qw: number;
} {
  const from = new THREE.Vector3(0, 0, 1); // normal padrão do PlaneGeometry
  const to = new THREE.Vector3(normal[0], normal[1], normal[2]).normalize();
  const q = new THREE.Quaternion().setFromUnitVectors(from, to);
  return { qx: q.x, qy: q.y, qz: q.z, qw: q.w };
}

/**
 * Calcula a bounding box de cada peça filtrando os vértices pelo lado de cada plano.
 *
 * Para N planos, existem N+1 peças:
 * - Peça 0: top do plano 0 (dot(n0,p) >= offset0)
 * - Peça 1: bottom do plano 0 E top do plano 1
 * - ...
 * - Peça N: bottom de todos os planos
 *
 * @param positions Float32Array com [x0,y0,z0, x1,y1,z1, ...]
 * @param cutPlanes Planos de corte no estado atual
 * @param plate Mesa de trabalho selecionada (para verificar fit)
 */
function computePieceBboxes(
  positions: Float32Array,
  cutPlanes: CutPlaneData[],
  plate: BuildPlate | null,
): PieceBboxStatus[] {
  const N = cutPlanes.length;
  if (N === 0) return [];

  // Pré-computar normais e offsets (evita recomputar por vértice)
  const normals = cutPlanes.map((cp) =>
    new THREE.Vector3(0, 0, 1)
      .applyQuaternion(new THREE.Quaternion(cp.qx, cp.qy, cp.qz, cp.qw))
      .normalize(),
  );
  const offsets = cutPlanes.map((cp, j) =>
    normals[j].dot(new THREE.Vector3(cp.px, cp.py, cp.pz)),
  );

  const numPieces = N + 1;
  const bboxes: PieceBboxStatus[] = Array.from({ length: numPieces }, (_, i) => ({
    pieceIndex: i,
    bbox: null,
    fits: true,
  }));

  // Inicializar min/max para cada peça
  const mins = Array.from({ length: numPieces }, () => [
    Infinity, Infinity, Infinity,
  ]);
  const maxs = Array.from({ length: numPieces }, () => [
    -Infinity, -Infinity, -Infinity,
  ]);

  const EPSILON = 1e-4;

  for (let vi = 0; vi < positions.length; vi += 3) {
    const px = positions[vi];
    const py = positions[vi + 1];
    const pz = positions[vi + 2];

    let assignedPiece = -1;

    // Verificar se o vértice pertence a um dos apêndices (peças 0..N-1)
    for (let j = 0; j < N; j++) {
      const sd =
        normals[j].x * px +
        normals[j].y * py +
        normals[j].z * pz -
        offsets[j];

      if (sd >= -EPSILON) {
        const cp = cutPlanes[j];
        if (cp.bbox_min && cp.bbox_max) {
          const inBox =
            px >= cp.bbox_min[0] - 8.0 &&
            px <= cp.bbox_max[0] + 8.0 &&
            py >= cp.bbox_min[1] - 8.0 &&
            py <= cp.bbox_max[1] + 8.0 &&
            pz >= cp.bbox_min[2] - 8.0 &&
            pz <= cp.bbox_max[2] + 8.0;
          if (inBox) {
            assignedPiece = j;
            break;
          }
        } else {
          assignedPiece = j;
          break;
        }
      }
    }

    // Se não pertence a nenhum apêndice anterior, pertence ao corpo restante (peça N)
    if (assignedPiece === -1) {
      assignedPiece = N;
    }

    if (px < mins[assignedPiece][0]) mins[assignedPiece][0] = px;
    if (py < mins[assignedPiece][1]) mins[assignedPiece][1] = py;
    if (pz < mins[assignedPiece][2]) mins[assignedPiece][2] = pz;
    if (px > maxs[assignedPiece][0]) maxs[assignedPiece][0] = px;
    if (py > maxs[assignedPiece][1]) maxs[assignedPiece][1] = py;
    if (pz > maxs[assignedPiece][2]) maxs[assignedPiece][2] = pz;
  }

  // Construir resultados
  for (let i = 0; i < numPieces; i++) {
    if (mins[i][0] === Infinity) {
      // Peça vazia
      bboxes[i] = { pieceIndex: i, bbox: null, fits: true };
      continue;
    }
    const bbox = {
      x: maxs[i][0] - mins[i][0],
      y: maxs[i][1] - mins[i][1],
      z: maxs[i][2] - mins[i][2],
    };
    const center = {
      x: (maxs[i][0] + mins[i][0]) / 2,
      y: (maxs[i][1] + mins[i][1]) / 2,
      z: (maxs[i][2] + mins[i][2]) / 2,
    };
    const fits = plate
      ? bbox.x <= plate.build_volume_x_mm &&
        bbox.y <= plate.build_volume_y_mm &&
        bbox.z <= plate.build_volume_z_mm
      : true;
    bboxes[i] = { pieceIndex: i, bbox, center, minY: mins[i][1], fits };
  }

  return bboxes;
}

export function ModelViewer({
  model,
  buildPlates,
  hasSubscription = false,
}: ModelViewerProps) {
  // ── URL assinada do arquivo 3D ─────────────────────────────────────────
  const [signedUrl, setSignedUrl] = useState<string | null>(null);
  const [urlError, setUrlError] = useState<string | null>(null);

  // ── Dimensões do modelo ────────────────────────────────────────────────
  const [computedDims, setComputedDims] = useState<ModelDimensions | null>(null);

  // ── Mesa de trabalho selecionada ───────────────────────────────────────
  const [selectedPlateId, setSelectedPlateId] = useState<string | null>(
    () =>
      buildPlates.find((p) => p.is_default)?.id ?? buildPlates[0]?.id ?? null,
  );

  // ── Modo split — estado da máquina ────────────────────────────────────
  const [splitMode, setSplitMode] = useState<SplitMode>("idle");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [splitError, setSplitError] = useState<string | null>(null);

  // ── Planos de corte ───────────────────────────────────────────────────
  const [cutPlanes, setCutPlanes] = useState<CutPlaneData[]>([]);
  const [selectedPlaneId, setSelectedPlaneId] = useState<string | null>(null);
  const [transformMode, setTransformMode] = useState<"translate" | "rotate">(
    "translate",
  );

  // ── Status das peças (calculado no drag-end) ──────────────────────────
  const [pieceBboxes, setPieceBboxes] = useState<PieceBboxStatus[]>([]);

  // ── Modo de visualização: "editor" (ajuste de planos) ou "preview" (peças nas mesas) ─
  const [activeView, setActiveView] = useState<"editor" | "preview">("editor");

  // ── Mensagem explicativa quando nenhum corte é gerado ────────────────
  const [separateFeedback, setSeparateFeedback] = useState<string | null>(null);

  // ── Peças executadas (download) ───────────────────────────────────────
  const [executedPieces, setExecutedPieces] = useState<ExecutedPiece[]>([]);

  // ── Grupos de cor parsados do 3MF (para preview 3D das peças) ─────────
  const [colorGroups, setColorGroups] = useState<import("@/components/viewer/threemf-colored-object").ColorGroup[]>([]);
  const [colorPreviewMode, setColorPreviewMode] = useState(false);

  // ── Modo de ferramenta para arquivos 3MF ─────────────────────────────
  // "colors": separação por cor (ColorSplitPanel)
  // "linear": corte linear manual (SplitPanel)
  // Para STL, sempre é "linear" implicitamente.
  const [toolMode, setToolMode] = useState<"colors" | "linear">(
    model.format === "3mf" ? "colors" : "linear",
  );

  // ── Vértices do modelo (para cálculo local de bboxes) ────────────────
  const modelPositionsRef = useRef<Float32Array | null>(null);

  // ── Contador para IDs únicos de plano ────────────────────────────────
  const planeCounterRef = useRef(0);

  // Buscar URL assinada
  useEffect(() => {
    fetch(`/api/models/${model.id}/signed-url`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<{ url: string }>;
      })
      .then((data) => setSignedUrl(data.url))
      .catch(() =>
        setUrlError(
          "Não foi possível carregar o arquivo 3D. Tente recarregar a página.",
        ),
      );
  }, [model.id]);

  const handleBboxChange = useCallback((bbox: THREE.Box3) => {
    const size = new THREE.Vector3();
    bbox.getSize(size);
    setComputedDims({
      x: parseFloat(size.x.toFixed(2)),
      y: parseFloat(size.z.toFixed(2)),
      z: parseFloat(size.y.toFixed(2)),
    });
  }, []);

  // Armazenar posições de vértices quando a geometria estiver disponível
  const handleGeometryReady = useCallback((positions: Float32Array) => {
    modelPositionsRef.current = positions;
  }, []);

  // Recomputar bboxes das peças no drag-end
  const handleDragEnd = useCallback(() => {
    if (!modelPositionsRef.current) return;
    const plate = buildPlates.find((p) => p.id === selectedPlateId) ?? null;
    const result = computePieceBboxes(
      modelPositionsRef.current,
      cutPlanes,
      plate,
    );
    setPieceBboxes(result);
  }, [cutPlanes, selectedPlateId, buildPlates]);

  // Preferir dimensões do banco (mais precisas)
  const dims = useMemo<ModelDimensions | null>(() => {
    if (
      model.bounding_box_x_mm != null &&
      model.bounding_box_y_mm != null &&
      model.bounding_box_z_mm != null
    ) {
      return {
        x: model.bounding_box_x_mm,
        y: model.bounding_box_y_mm,
        z: model.bounding_box_z_mm,
      };
    }
    return computedDims;
  }, [model, computedDims]);

  const selectedPlate =
    buildPlates.find((p) => p.id === selectedPlateId) ?? null;

  // ── Ações da máquina de estado split ─────────────────────────────────

  const handleStartSplit = useCallback(async () => {
    if (!selectedPlateId) return;
    setSplitMode("loading");
    setSplitError(null);

    try {
      const res = await fetch("/api/split-sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model_id: model.id,
          build_plate_id: selectedPlateId,
        }),
      });
      if (!res.ok) {
        const err = (await res.json()) as { detail?: string };
        throw new Error(err.detail ?? `HTTP ${res.status}`);
      }
      const data = (await res.json()) as PlanSessionResponse;
      setSessionId(data.split_session_id);

      // Converter planos sugeridos → CutPlaneData com quaternion e source
      const initialPlanes: CutPlaneData[] = data.cut_planes.map((cp) => {
        const q = quaternionFromNormal(cp.normal);
        planeCounterRef.current += 1;
        return {
          id: `plane-${planeCounterRef.current}`,
          px: cp.origin[0],
          py: cp.origin[1],
          pz: cp.origin[2],
          ...q,
          label: cp.label,
          source: cp.source, // "suggested_natural" | "suggested_grid_fallback"
        };
      });

      setCutPlanes(initialPlanes);
      setPieceBboxes([]);
      setSplitMode("planning");
    } catch (err) {
      setSplitError(String(err));
      setSplitMode("error");
    }
  }, [model.id, selectedPlateId]);

  /** Aciona a análise automática de gargalos naturais para a sessão atual. */
  const handleAutoSuggest = useCallback(async () => {
    if (!sessionId) return;
    setSplitMode("suggesting");
    setSplitError(null);

    try {
      const res = await fetch(`/api/split-sessions/${sessionId}/suggest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!res.ok) {
        const err = (await res.json()) as { detail?: string };
        throw new Error(err.detail ?? `HTTP ${res.status}`);
      }
      const data = (await res.json()) as SuggestResponse;

      // Substituir planos pelos sugeridos automaticamente
      const newPlanes: CutPlaneData[] = data.cut_planes.map((cp) => {
        const q = quaternionFromNormal(cp.normal);
        planeCounterRef.current += 1;
        return {
          id: `plane-${planeCounterRef.current}`,
          px: cp.origin[0],
          py: cp.origin[1],
          pz: cp.origin[2],
          ...q,
          label: cp.label,
          source: cp.source as CutPlaneData["source"],
        };
      });

      setCutPlanes(newPlanes);
      setSelectedPlaneId(null);

      // Calcular imediatamente o status de fit das peças resultantes
      // (sem esperar o usuário arrastar um plano)
      if (modelPositionsRef.current && newPlanes.length > 0) {
        const plate = buildPlates.find((p) => p.id === selectedPlateId) ?? null;
        const bboxes = computePieceBboxes(modelPositionsRef.current, newPlanes, plate);
        setPieceBboxes(bboxes);
        setActiveView("preview");
      } else {
        setPieceBboxes([]);
        setActiveView("editor");
      }

      setSplitMode("planning");
    } catch (err) {
      // Não sai do modo planning — só mostra erro
      setSplitError(String(err));
      setSplitMode("planning");
    }
  }, [sessionId, buildPlates, selectedPlateId]);

  /**
   * Inicia a separação estrutural por esqueleto 3D.
   * Cria uma nova sessão (se não existir), dispara o job assíncrono e
   * faz polling a cada 2s até o resultado ficar pronto.
   */
  const handleSeparateParts = useCallback(async (sensitivity: number) => {
    if (!selectedPlateId) return;
    setSplitMode("separating");
    setSplitError(null);

    try {
      // 1. Garantir que há uma sessão ativa — criar uma nova se necessário
      let activeSessionId = sessionId;
      if (!activeSessionId) {
        const res = await fetch("/api/split-sessions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model_id: model.id, build_plate_id: selectedPlateId }),
        });
        if (!res.ok) {
          const err = (await res.json()) as { detail?: string };
          throw new Error(err.detail ?? `HTTP ${res.status}`);
        }
        const data = (await res.json()) as { split_session_id: string };
        activeSessionId = data.split_session_id;
        setSessionId(activeSessionId);
      }

      // 2. Disparar o job de separação estrutural
      const sepRes = await fetch(`/api/split-sessions/${activeSessionId}/separate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ structural_sensitivity: sensitivity }),
      });
      if (!sepRes.ok) {
        const err = (await sepRes.json()) as { detail?: string };
        throw new Error(err.detail ?? `HTTP ${sepRes.status}`);
      }

      // 3. Polling a cada 2s até status = completed | failed
      let attempts = 0;
      const maxAttempts = 60; // 60 × 2s = 2 minutos máximo
      const poll = async (): Promise<void> => {
        if (attempts >= maxAttempts) {
          throw new Error("Tempo limite excedido. Tente novamente.");
        }
        attempts++;

        const statusRes = await fetch(
          `/api/split-sessions/${activeSessionId}/status`,
          { method: "GET" },
        );
        if (!statusRes.ok) throw new Error(`Polling falhou: HTTP ${statusRes.status}`);

        const statusData = (await statusRes.json()) as StatusPollingResponse;

        if (statusData.status === "completed") {
          // Converter planos retornados → CutPlaneData com quaternion
          const newPlanes: CutPlaneData[] = statusData.cut_planes.map((cp) => {
            const q = quaternionFromNormal(cp.normal);
            planeCounterRef.current += 1;
            return {
              id: `plane-${planeCounterRef.current}`,
              px: cp.origin[0],
              py: cp.origin[1],
              pz: cp.origin[2],
              ...q,
              label: cp.label,
              source: cp.source as CutPlaneData["source"],
              structural_group: cp.structural_group ?? null,
              bbox_min: (cp as { bbox_min?: [number, number, number] | null }).bbox_min ?? null,
              bbox_max: (cp as { bbox_max?: [number, number, number] | null }).bbox_max ?? null,
            };
          });

          setCutPlanes(newPlanes);
          setSelectedPlaneId(null);

          // Calcular bboxes imediatamente
          if (modelPositionsRef.current && newPlanes.length > 0) {
            const plate = buildPlates.find((p) => p.id === selectedPlateId) ?? null;
            const bboxes = computePieceBboxes(modelPositionsRef.current, newPlanes, plate);
            setPieceBboxes(bboxes);
            setSeparateFeedback(null);
            // Mostrar graficamente as peças separadas nas mesas de trabalho
            setActiveView("preview");
          } else {
            setPieceBboxes([]);
            setSeparateFeedback(
              `Nenhum apêndice atingiu o limiar de ${(sensitivity * 100).toFixed(0)}% do volume total. ` +
              `Dica: reduza o controle de sensibilidade (ex: 3% ou 5%) para identificar apêndices mais finos como asas, caudas ou chifres, e clique novamente em "Separar Peças".`
            );
            setActiveView("editor");
          }

          setSplitMode("planning");
        } else if (statusData.status === "failed") {
          throw new Error(statusData.error_message ?? "Separação estrutural falhou.");
        } else {
          // Ainda processando — aguardar 2s e tentar novamente
          await new Promise<void>((resolve) => setTimeout(resolve, 2000));
          return poll();
        }
      };

      await poll();
    } catch (err) {
      setSplitError(String(err));
      // Se já há sessão, voltar para planning; senão, erro
      setSplitMode(sessionId ? "planning" : "error");
    }
  }, [sessionId, model.id, selectedPlateId, buildPlates]);

  const handleAddPlane = useCallback(() => {
    planeCounterRef.current += 1;
    const newPlane: CutPlaneData = {
      id: `plane-${planeCounterRef.current}`,
      // Posicionar novo plano na origem com normal +Z (horizontal)
      px: 0,
      py: 0,
      pz: 0,
      qx: 0,
      qy: 0,
      qz: 0,
      qw: 1,
      label: "",
      source: "manual",
    };
    setCutPlanes((prev) => [...prev, newPlane]);
    setSelectedPlaneId(newPlane.id);
  }, []);


  const handleRemovePlane = useCallback((id: string) => {
    setCutPlanes((prev) => prev.filter((p) => p.id !== id));
    setPieceBboxes([]);
  }, []);

  const handleCutPlaneMoved = useCallback(
    (
      id: string,
      px: number,
      py: number,
      pz: number,
      qx: number,
      qy: number,
      qz: number,
      qw: number,
    ) => {
      setCutPlanes((prev) =>
        prev.map((p) =>
          p.id === id ? { ...p, px, py, pz, qx, qy, qz, qw } : p,
        ),
      );
    },
    [],
  );

  const handleExecute = useCallback(async () => {
    if (!sessionId || cutPlanes.length === 0) return;
    setSplitMode("executing");

    // Converter CutPlaneData para o formato do backend
    const planesPayload = cutPlanes.map((cp) => {
      const q = new THREE.Quaternion(cp.qx, cp.qy, cp.qz, cp.qw);
      const normal = new THREE.Vector3(0, 0, 1).applyQuaternion(q).normalize();
      return {
        normal: [normal.x, normal.y, normal.z],
        origin: [cp.px, cp.py, cp.pz],
        label: cp.label,
        bbox_min: cp.bbox_min ?? null,
        bbox_max: cp.bbox_max ?? null,
      };
    });

    try {
      const res = await fetch(`/api/split-sessions/${sessionId}/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cut_planes: planesPayload }),
      });

      if (!res.ok) {
        const errData = (await res.json()) as { detail?: string };
        const msg = errData.detail ?? `HTTP ${res.status}`;
        setSplitError(msg);
        setSplitMode("error");
        return;
      }

      const data = (await res.json()) as { pieces: ExecutedPiece[] };
      setExecutedPieces(data.pieces);
      setSplitMode("done");
    } catch (err) {
      setSplitError(String(err));
      setSplitMode("error");
    }
  }, [sessionId, cutPlanes]);

  const handleCancel = useCallback(() => {
    setSplitMode("idle");
    setCutPlanes([]);
    setSelectedPlaneId(null);
    setPieceBboxes([]);
    setSessionId(null);
    setSplitError(null);
    setActiveView("editor");
    setSeparateFeedback(null);
  }, []);

  // ── Renderização ──────────────────────────────────────────────────────

  if (urlError) {
    return (
      <div className="flex h-64 items-center justify-center rounded-xl border border-red-200 bg-red-50 text-sm text-red-600">
        {urlError}
      </div>
    );
  }

  const isInSplitMode =
    splitMode === "planning" ||
    splitMode === "suggesting" ||
    splitMode === "separating" ||
    splitMode === "executing";

  return (
    <div>
      <div className="relative overflow-hidden rounded-xl border border-gray-800 bg-gray-900 shadow-lg">
        {/* Toggle flutuante de visualização rápida no topo do canvas */}
        {isInSplitMode && cutPlanes.length > 0 && (
          <div className="absolute top-3 left-3 z-10 flex items-center gap-1 rounded-lg border border-gray-700/80 bg-gray-900/85 p-1 shadow-lg backdrop-blur-md">
            <button
              onClick={() => setActiveView("editor")}
              className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition ${
                activeView === "editor"
                  ? "bg-violet-600 text-white shadow-sm"
                  : "text-gray-300 hover:bg-gray-800 hover:text-white"
              }`}
            >
              ✏️ Editar Cortes
            </button>
            <button
              onClick={() => setActiveView("preview")}
              className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition ${
                activeView === "preview"
                  ? "bg-emerald-600 text-white shadow-sm"
                  : "text-gray-300 hover:bg-gray-800 hover:text-white"
              }`}
            >
              🧩 Peças nas Mesas ({cutPlanes.length + 1})
            </button>
          </div>
        )}

        {/* Canvas 3D */}
        <div style={{ height: 520 }}>
          {signedUrl ? (
            <ViewerScene
              url={signedUrl}
              format={model.format as "stl" | "3mf"}
              selectedPlate={selectedPlate}
              onBboxChange={handleBboxChange}
              splitMode={isInSplitMode}
              activeView={activeView}
              cutPlanes={cutPlanes}
              pieceBboxes={pieceBboxes}
              selectedPlaneId={selectedPlaneId}
              transformMode={transformMode}
              onSelectPlane={setSelectedPlaneId}
              onCutPlaneMoved={handleCutPlaneMoved}
              onDragEnd={handleDragEnd}
              onGeometryReady={handleGeometryReady}
              colorPreviewMode={colorPreviewMode}
              colorGroups={colorGroups}
              onGroupsParsed={setColorGroups}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-gray-500">
              {urlError ?? "Carregando arquivo…"}
            </div>
          )}
        </div>

        {/* Overlay de visualização (exibido apenas fora do modo split) */}
        {!isInSplitMode && splitMode !== "done" && (
          <ViewerOverlay
            dims={dims}
            buildPlates={buildPlates}
            selectedPlateId={selectedPlateId}
            onPlateChange={setSelectedPlateId}
          />
        )}
      </div>

      {/* Painel de download (exibido após execução bem-sucedida) */}
      {splitMode === "done" && executedPieces.length > 0 && (
        <PieceDownload
          pieces={executedPieces}
          onClose={handleCancel}
        />
      )}

      {/* ── Seletor de modo de ferramenta (apenas para 3MF, quando idle) ── */}
      {splitMode === "idle" && model.format === "3mf" && (
        <div className="mt-4 flex gap-2 rounded-xl border border-gray-200 bg-white p-1">
          <button
            onClick={() => {
              setToolMode("colors");
              setColorPreviewMode(false);
            }}
            className={`flex-1 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
              toolMode === "colors"
                ? "bg-violet-600 text-white shadow-sm"
                : "text-gray-500 hover:bg-gray-100 hover:text-gray-700"
            }`}
          >
            🎨 Separar por Cores
          </button>
          <button
            onClick={() => setToolMode("linear")}
            className={`flex-1 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
              toolMode === "linear"
                ? "bg-violet-600 text-white shadow-sm"
                : "text-gray-500 hover:bg-gray-100 hover:text-gray-700"
            }`}
          >
            ✂️ Corte Linear
          </button>
        </div>
      )}

      {/* ── Painel de separação por cor ─────────────────────────────────── */}
      {splitMode === "idle" && model.format === "3mf" && toolMode === "colors" && (
        <ColorSplitPanel
          modelId={model.id}
          modelFormat={model.format}
          buildPlates={buildPlates}
          selectedPlateId={selectedPlateId}
          onPlateChange={setSelectedPlateId}
          hasSubscription={hasSubscription}
          onShowPreview={colorGroups.length > 0 ? () => setColorPreviewMode((v) => !v) : undefined}
          colorPreviewMode={colorPreviewMode}
        />
      )}

      {/* ── Painel de corte linear (idle para 3MF com toolMode=linear, ou STL) ── */}
      {splitMode === "idle" && (model.format !== "3mf" || toolMode === "linear") && (
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
          onViewChange={setActiveView}
          separateFeedback={separateFeedback}
          onStartSplit={handleStartSplit}
          onAutoSuggest={handleAutoSuggest}
          onSeparateParts={handleSeparateParts}
          onAddPlane={handleAddPlane}
          onRemovePlane={handleRemovePlane}
          onSelectPlane={setSelectedPlaneId}
          onSetTransformMode={setTransformMode}
          onExecute={handleExecute}
          onCancel={handleCancel}
          onPlateChange={setSelectedPlateId}
        />
      )}

      {/* ── Painel de corte linear em progresso (não-idle) ──────────────── */}
      {splitMode !== "done" && splitMode !== "idle" && (
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
          onViewChange={setActiveView}
          separateFeedback={separateFeedback}
          onStartSplit={handleStartSplit}
          onAutoSuggest={handleAutoSuggest}
          onSeparateParts={handleSeparateParts}
          onAddPlane={handleAddPlane}
          onRemovePlane={handleRemovePlane}
          onSelectPlane={setSelectedPlaneId}
          onSetTransformMode={setTransformMode}
          onExecute={handleExecute}
          onCancel={handleCancel}
          onPlateChange={setSelectedPlateId}
        />
      )}
    </div>
  );
}

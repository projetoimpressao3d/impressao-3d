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
} from "@/types/database";
import { ViewerOverlay } from "./viewer-overlay";
import { SplitPanel } from "@/components/split/split-panel";
import { PieceDownload } from "@/components/split/piece-download";

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

    for (let pieceIdx = 0; pieceIdx < numPieces; pieceIdx++) {
      let inPiece = true;

      if (pieceIdx < N) {
        // Verificar planos 0..pieceIdx
        for (let j = 0; j <= pieceIdx; j++) {
          const sd =
            normals[j].x * px +
            normals[j].y * py +
            normals[j].z * pz -
            offsets[j];

          if (j < pieceIdx && sd > EPSILON) {
            // Deve estar no lado "bottom" do plano j
            inPiece = false;
            break;
          }
          if (j === pieceIdx && sd < -EPSILON) {
            // Deve estar no lado "top" do plano pieceIdx
            inPiece = false;
            break;
          }
        }
      } else {
        // Última peça: bottom de TODOS os planos
        for (let j = 0; j < N; j++) {
          const sd =
            normals[j].x * px +
            normals[j].y * py +
            normals[j].z * pz -
            offsets[j];
          if (sd > EPSILON) {
            inPiece = false;
            break;
          }
        }
      }

      if (inPiece) {
        if (px < mins[pieceIdx][0]) mins[pieceIdx][0] = px;
        if (py < mins[pieceIdx][1]) mins[pieceIdx][1] = py;
        if (pz < mins[pieceIdx][2]) mins[pieceIdx][2] = pz;
        if (px > maxs[pieceIdx][0]) maxs[pieceIdx][0] = px;
        if (py > maxs[pieceIdx][1]) maxs[pieceIdx][1] = py;
        if (pz > maxs[pieceIdx][2]) maxs[pieceIdx][2] = pz;
      }
    }
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
    const fits = plate
      ? bbox.x <= plate.build_volume_x_mm &&
        bbox.y <= plate.build_volume_y_mm &&
        bbox.z <= plate.build_volume_z_mm
      : true;
    bboxes[i] = { pieceIndex: i, bbox, fits };
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

  // ── Peças executadas (download) ───────────────────────────────────────
  const [executedPieces, setExecutedPieces] = useState<ExecutedPiece[]>([]);

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

      // Converter planos sugeridos em CutPlaneData com quaternion
      const initialPlanes: CutPlaneData[] = data.cut_planes.map((cp) => {
        const q = quaternionFromNormal(cp.normal);
        const pos = { x: 0, y: 0, z: 0 };
        if (cp.axis === "x") pos.x = cp.position_mm;
        else if (cp.axis === "y") pos.y = cp.position_mm;
        else pos.z = cp.position_mm;

        planeCounterRef.current += 1;
        return {
          id: `plane-${planeCounterRef.current}`,
          px: pos.x,
          py: pos.y,
          pz: pos.z,
          ...q,
          label: cp.label,
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
    splitMode === "planning" || splitMode === "executing";

  return (
    <div>
      <div className="overflow-hidden rounded-xl border border-gray-800 bg-gray-900 shadow-lg">
        {/* Canvas 3D */}
        <div style={{ height: 520 }}>
          {signedUrl ? (
            <ViewerScene
              url={signedUrl}
              format={model.format as "stl" | "3mf"}
              selectedPlate={selectedPlate}
              onBboxChange={handleBboxChange}
              splitMode={isInSplitMode}
              cutPlanes={cutPlanes}
              selectedPlaneId={selectedPlaneId}
              transformMode={transformMode}
              onSelectPlane={setSelectedPlaneId}
              onCutPlaneMoved={handleCutPlaneMoved}
              onDragEnd={handleDragEnd}
              onGeometryReady={handleGeometryReady}
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

      {/* Painel do editor de cortes */}
      {splitMode !== "done" && (
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
          onStartSplit={handleStartSplit}
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

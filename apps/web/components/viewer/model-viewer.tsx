"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import dynamic from "next/dynamic";
import * as THREE from "three";
import type { BuildPlate, Model } from "@/types/database";
import { ViewerOverlay } from "./viewer-overlay";

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

interface ModelViewerProps {
  model: Model;
  buildPlates: BuildPlate[];
}

export function ModelViewer({ model, buildPlates }: ModelViewerProps) {
  const [signedUrl, setSignedUrl] = useState<string | null>(null);
  const [urlError, setUrlError] = useState<string | null>(null);
  const [computedDims, setComputedDims] = useState<ModelDimensions | null>(null);
  const [selectedPlateId, setSelectedPlateId] = useState<string | null>(
    () =>
      buildPlates.find((p) => p.is_default)?.id ?? buildPlates[0]?.id ?? null,
  );

  // Buscar URL assinada de download para o visualizador
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

  // Callback chamado pelo ViewerScene quando a geometria é carregada e centrada
  // THREE.js: Y=cima. STL típico de slicer: Z=cima.
  // Reportamos o tamanho bruto da bbox (eixo x→x, z→y, y→z) para aproximar as coords de impressão
  const handleBboxChange = useCallback((bbox: THREE.Box3) => {
    const size = new THREE.Vector3();
    bbox.getSize(size);
    setComputedDims({
      x: parseFloat(size.x.toFixed(2)),
      y: parseFloat(size.z.toFixed(2)), // three Z → profundidade Y
      z: parseFloat(size.y.toFixed(2)), // three Y → altura Z
    });
  }, []);

  // Preferir dimensões do banco (calculadas pelo trimesh no servidor, mais precisas)
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

  if (urlError) {
    return (
      <div className="flex h-64 items-center justify-center rounded-xl border border-red-200 bg-red-50 text-sm text-red-600">
        {urlError}
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-gray-800 bg-gray-900 shadow-lg">
      {/* Canvas 3D */}
      <div style={{ height: 520 }}>
        {signedUrl ? (
          <ViewerScene
            url={signedUrl}
            format={model.format as "stl" | "3mf"}
            selectedPlate={selectedPlate}
            onBboxChange={handleBboxChange}
          />
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-gray-500">
            {urlError ? urlError : "Carregando arquivo…"}
          </div>
        )}
      </div>

      {/* Overlay: dimensões + seletor de mesa */}
      <ViewerOverlay
        dims={dims}
        buildPlates={buildPlates}
        selectedPlateId={selectedPlateId}
        onPlateChange={setSelectedPlateId}
      />
    </div>
  );
}

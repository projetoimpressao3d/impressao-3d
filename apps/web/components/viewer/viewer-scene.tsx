"use client";

import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { Suspense } from "react";
import type * as THREE from "three";
import type { BuildPlate, CutPlaneData } from "@/types/database";
import { STLMesh } from "./stl-mesh";
import { ThreeMFObject } from "./threemf-object";
import { BuildPlateBox } from "./build-plate-box";
import { SplitEditor } from "./split-editor";

interface ViewerSceneProps {
  url: string;
  format: "stl" | "3mf";
  selectedPlate: BuildPlate | null;
  onBboxChange: (bbox: THREE.Box3) => void;
  // Props do modo de edição de cortes (opcionais)
  splitMode?: boolean;
  cutPlanes?: CutPlaneData[];
  selectedPlaneId?: string | null;
  transformMode?: "translate" | "rotate";
  onSelectPlane?: (id: string | null) => void;
  onCutPlaneMoved?: (
    id: string,
    px: number,
    py: number,
    pz: number,
    qx: number,
    qy: number,
    qz: number,
    qw: number,
  ) => void;
  onDragEnd?: () => void;
  onGeometryReady?: (positions: Float32Array) => void;
}

/**
 * Componente do canvas 3D (Three.js/R3F).
 * DEVE ser importado dinamicamente com ssr: false — não pode rodar no servidor.
 *
 * Em splitMode=true: renderiza SplitEditor (modelo semi-transparente + planos de corte).
 * Em splitMode=false: renderiza o visualizador normal.
 */
export function ViewerScene({
  url,
  format,
  selectedPlate,
  onBboxChange,
  splitMode = false,
  cutPlanes = [],
  selectedPlaneId = null,
  transformMode = "translate",
  onSelectPlane,
  onCutPlaneMoved,
  onDragEnd,
  onGeometryReady,
}: ViewerSceneProps) {
  return (
    <Canvas
      camera={{ position: [0, 120, 280], fov: 45, near: 0.1, far: 100000 }}
      gl={{ antialias: true, alpha: false }}
      style={{ background: "#111827" }}
      // Desseleciona plano ao clicar no fundo (apenas no modo split)
      onPointerMissed={splitMode ? () => onSelectPlane?.(null) : undefined}
    >
      {/* Iluminação */}
      <ambientLight intensity={0.5} />
      <directionalLight
        position={[200, 400, 300]}
        intensity={1.2}
        castShadow={false}
      />
      <directionalLight position={[-150, -100, -200]} intensity={0.25} />
      <hemisphereLight args={["#4a6080", "#1a1a2e", 0.4]} />

      {/* Grade de referência no chão */}
      <gridHelper args={[2000, 200, "#334155", "#1e293b"]} />

      <Suspense fallback={null}>
        {splitMode ? (
          /* Modo de edição de cortes — SplitEditor gerencia todo o conteúdo da cena */
          <SplitEditor
            url={url}
            format={format}
            selectedPlate={selectedPlate}
            cutPlanes={cutPlanes}
            selectedPlaneId={selectedPlaneId}
            transformMode={transformMode}
            onBboxChange={onBboxChange}
            onSelectPlane={onSelectPlane ?? (() => {})}
            onCutPlaneMoved={onCutPlaneMoved ?? (() => {})}
            onDragEnd={onDragEnd ?? (() => {})}
            onGeometryReady={onGeometryReady ?? (() => {})}
          />
        ) : (
          /* Modo de visualização normal */
          <>
            {format === "stl" ? (
              <STLMesh url={url} onBboxChange={onBboxChange} />
            ) : (
              <ThreeMFObject url={url} onBboxChange={onBboxChange} />
            )}

            {/* Caixa da mesa de trabalho selecionada */}
            {selectedPlate && <BuildPlateBox plate={selectedPlate} />}

            {/* Controles de câmera: rotação, zoom, pan */}
            <OrbitControls
              enablePan
              enableZoom
              enableRotate
              makeDefault
              minDistance={1}
              maxDistance={15000}
              zoomSpeed={1.2}
              panSpeed={0.8}
            />
          </>
        )}
      </Suspense>
    </Canvas>
  );
}

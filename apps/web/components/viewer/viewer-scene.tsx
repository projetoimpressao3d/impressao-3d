"use client";

import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { Suspense } from "react";
import type * as THREE from "three";
import type { BuildPlate } from "@/types/database";
import { STLMesh } from "./stl-mesh";
import { ThreeMFObject } from "./threemf-object";
import { BuildPlateBox } from "./build-plate-box";

interface ViewerSceneProps {
  url: string;
  format: "stl" | "3mf";
  selectedPlate: BuildPlate | null;
  onBboxChange: (bbox: THREE.Box3) => void;
}

/**
 * Componente do canvas 3D (Three.js).
 * DEVE ser importado dinamicamente com ssr: false — não pode rodar no servidor.
 */
export function ViewerScene({
  url,
  format,
  selectedPlate,
  onBboxChange,
}: ViewerSceneProps) {
  return (
    <Canvas
      camera={{ position: [0, 120, 280], fov: 45, near: 0.1, far: 100000 }}
      gl={{ antialias: true, alpha: false }}
      style={{ background: "#111827" }}
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

      {/* Modelo 3D — envolvido em Suspense para o useLoader */}
      <Suspense fallback={null}>
        {format === "stl" ? (
          <STLMesh url={url} onBboxChange={onBboxChange} />
        ) : (
          <ThreeMFObject url={url} onBboxChange={onBboxChange} />
        )}

        {/* Caixa da mesa de trabalho selecionada */}
        {selectedPlate && <BuildPlateBox plate={selectedPlate} />}
      </Suspense>

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
    </Canvas>
  );
}

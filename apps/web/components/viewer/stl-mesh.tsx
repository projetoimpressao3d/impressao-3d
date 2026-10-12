"use client";

import { useLoader } from "@react-three/fiber";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { useEffect, useMemo } from "react";
import * as THREE from "three";

import type { BuildPlate } from "@/types/database";

export interface STLMeshProps {
  url: string;
  selectedPlate?: BuildPlate | null;
  onBboxChange: (bbox: THREE.Box3) => void;
  /** Callback com as posições de vértices (após centralização) para cálculo de bboxes por peça. */
  onGeometryReady?: (positions: Float32Array) => void;
  /** Opacidade do material (padrão: 1.0). Valores < 1 habilitam transparência. */
  opacity?: number;
}

/**
 * Carrega um arquivo STL e o renderiza como mesh.
 * Centra a geometria horizontalmente e apoia a base no piso da mesa (Z=0).
 * Chama onBboxChange com a bounding box original.
 * Chama onGeometryReady (opcional) com as posições de vértices após centralização.
 */
export function STLMesh({
  url,
  selectedPlate,
  onBboxChange,
  onGeometryReady,
  opacity = 1,
}: STLMeshProps) {
  const geometry = useLoader(STLLoader, url);

  // Calcular bounding box ANTES de centrar (preserva dimensões reais)
  useEffect(() => {
    const geo = geometry.clone();
    geo.computeBoundingBox();
    if (geo.boundingBox) {
      onBboxChange(geo.boundingBox.clone());
    }
  }, [geometry, onBboxChange]);

  // Processar geometria: centrar horizontalmente + base em Y=0 + normais
  const processedGeometry = useMemo(() => {
    const geo = geometry.clone();
    geo.computeBoundingBox();
    const bbox = geo.boundingBox!;
    const cx = (bbox.min.x + bbox.max.x) / 2;
    const cz = (bbox.min.z + bbox.max.z) / 2;
    const minY = bbox.min.y;
    geo.translate(-cx, -minY, -cz);
    geo.computeVertexNormals();
    return geo;
  }, [geometry]);

  // Expor posições de vértices (após centralização) para o editor de cortes
  useEffect(() => {
    if (onGeometryReady && processedGeometry.attributes.position) {
      onGeometryReady(
        processedGeometry.attributes.position.array as Float32Array,
      );
    }
  }, [processedGeometry, onGeometryReady]);

  const floorY = selectedPlate ? -(selectedPlate.build_volume_z_mm ?? 256) / 2 : 0;

  return (
    <mesh position={[0, floorY, 0]} geometry={processedGeometry} castShadow receiveShadow>
      <meshStandardMaterial
        color="#6366f1"
        roughness={0.45}
        metalness={0.1}
        side={THREE.DoubleSide}
        transparent={opacity < 1}
        opacity={opacity}
      />
    </mesh>
  );
}

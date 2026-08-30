"use client";

import { useLoader } from "@react-three/fiber";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { useEffect, useMemo } from "react";
import * as THREE from "three";

interface STLMeshProps {
  url: string;
  onBboxChange: (bbox: THREE.Box3) => void;
  /** Callback com as posições de vértices (após centralização) para cálculo de bboxes por peça. */
  onGeometryReady?: (positions: Float32Array) => void;
  /** Opacidade do material (padrão: 1.0). Valores < 1 habilitam transparência. */
  opacity?: number;
}

/**
 * Carrega um arquivo STL e o renderiza como mesh.
 * Centra a geometria na origem e computa normais de vértice para iluminação suave.
 * Chama onBboxChange com a bounding box original (antes de centrar).
 * Chama onGeometryReady (opcional) com as posições de vértices após centralização,
 * usadas pelo editor de cortes para calcular a bounding box de cada peça.
 */
export function STLMesh({ url, onBboxChange, onGeometryReady, opacity = 1 }: STLMeshProps) {
  const geometry = useLoader(STLLoader, url);

  // Calcular bounding box ANTES de centrar (preserva dimensões reais)
  useEffect(() => {
    const geo = geometry.clone();
    geo.computeBoundingBox();
    if (geo.boundingBox) {
      onBboxChange(geo.boundingBox.clone());
    }
  }, [geometry, onBboxChange]);

  // Processar geometria: centrar + normais — memo para não recalcular a cada render
  const processedGeometry = useMemo(() => {
    const geo = geometry.clone();
    geo.computeBoundingBox();
    geo.center(); // centralizar na origem
    geo.computeVertexNormals(); // normais suaves para boa iluminação
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

  return (
    <mesh geometry={processedGeometry} castShadow receiveShadow>
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

"use client";

import {
  useState,
  useCallback,
  useRef,
  useEffect,
  useMemo,
} from "react";
import { useThree } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import type { BuildPlate, CutPlaneData, PieceBboxStatus } from "@/types/database";
import { STLMesh } from "./stl-mesh";
import { ThreeMFObject } from "./threemf-object";
import { BuildPlateBox } from "./build-plate-box";
import { CutPlaneMesh } from "./cut-plane-mesh";

interface SplitEditorProps {
  url: string;
  format: "stl" | "3mf";
  selectedPlate: BuildPlate | null;
  cutPlanes: CutPlaneData[];
  selectedPlaneId: string | null;
  transformMode: "translate" | "rotate";
  onBboxChange: (bbox: THREE.Box3) => void;
  onSelectPlane: (id: string | null) => void;
  onCutPlaneMoved: (
    id: string,
    px: number,
    py: number,
    pz: number,
    qx: number,
    qy: number,
    qz: number,
    qw: number,
  ) => void;
  onDragEnd: () => void;
  onGeometryReady: (positions: Float32Array) => void;
}

/**
 * Composição da cena em modo de edição de cortes.
 *
 * Responsabilidades:
 * - Habilita localClippingEnabled no renderer
 * - Renderiza o modelo semi-transparente
 * - Renderiza os discos de plano de corte com TransformControls
 * - Renderiza a caixa da mesa de trabalho
 * - Desseleciona ao clicar no fundo (onPointerMissed)
 */
export function SplitEditor({
  url,
  format,
  selectedPlate,
  cutPlanes,
  selectedPlaneId,
  transformMode,
  onBboxChange,
  onSelectPlane,
  onCutPlaneMoved,
  onDragEnd,
  onGeometryReady,
}: SplitEditorProps) {
  const { gl } = useThree();

  // Habilitar clipping local para material.clippingPlanes funcionar por mesh
  useEffect(() => {
    gl.localClippingEnabled = true;
    return () => {
      gl.localClippingEnabled = false;
    };
  }, [gl]);

  // Calcular raio do disco de corte baseado na bbox do modelo
  const [diskRadius, setDiskRadius] = useState(150);
  const handleBboxChange = useCallback(
    (bbox: THREE.Box3) => {
      const size = new THREE.Vector3();
      bbox.getSize(size);
      const maxDim = Math.max(size.x, size.y, size.z);
      setDiskRadius(Math.max(maxDim * 0.8, 50));
      onBboxChange(bbox);
    },
    [onBboxChange],
  );

  return (
    <>
      {/* Modelo renderizado semi-transparente durante edição */}
      {format === "stl" ? (
        <STLMesh
          url={url}
          onBboxChange={handleBboxChange}
          onGeometryReady={onGeometryReady}
          opacity={0.45}
        />
      ) : (
        <ThreeMFObject
          url={url}
          onBboxChange={handleBboxChange}
          onGeometryReady={onGeometryReady}
          opacity={0.45}
        />
      )}

      {/* Mesa de trabalho */}
      {selectedPlate && <BuildPlateBox plate={selectedPlate} />}

      {/* Planos de corte */}
      {cutPlanes.map((plane) => (
        <CutPlaneMesh
          key={plane.id}
          plane={plane}
          isSelected={selectedPlaneId === plane.id}
          transformMode={transformMode}
          diskRadius={diskRadius}
          onSelect={onSelectPlane}
          onPlaneMoved={onCutPlaneMoved}
          onDragEnd={onDragEnd}
        />
      ))}

      {/* Controles de câmera — makeDefault permite que TransformControls os desabilite */}
      <OrbitControls
        makeDefault
        enablePan
        enableZoom
        enableRotate
        minDistance={1}
        maxDistance={15000}
        zoomSpeed={1.2}
        panSpeed={0.8}
      />
    </>
  );
}

"use client";

import { useRef, useCallback } from "react";
import { TransformControls } from "@react-three/drei";
import * as THREE from "three";
import type { CutPlaneData } from "@/types/database";

interface CutPlaneMeshProps {
  plane: CutPlaneData;
  isSelected: boolean;
  transformMode: "translate" | "rotate";
  diskRadius: number;
  onSelect: (id: string) => void;
  onPlaneMoved: (
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
}

/**
 * Cores por origem do plano de corte:
 * - suggested_natural:       roxo  (#7c3aed / #a78bfa)
 * - suggested_grid_fallback: âmbar (#b45309 / #d97706)
 * - manual:                  cinza (#4b5563 / #6b7280)
 * Quando selecionado, sempre âmbar brilhante (#f59e0b).
 */
function getPlaneColors(
  source: CutPlaneData["source"],
  isSelected: boolean,
): { fill: string; border: string } {
  if (isSelected) return { fill: "#f59e0b", border: "#f59e0b" };
  switch (source) {
    case "suggested_natural":
      return { fill: "#a78bfa", border: "#7c3aed" };
    case "suggested_grid_fallback":
      return { fill: "#d97706", border: "#b45309" };
    case "manual":
    default:
      return { fill: "#6b7280", border: "#4b5563" };
  }
}

/**
 * Disco visual de um plano de corte + TransformControls quando selecionado.
 *
 * - PlaneGeometry com normal padrão [0,0,1] (plano XY)
 * - Quaternion aplicado via prop `quaternion` do mesh
 * - Cor varia conforme `source` do plano (natural/grade/manual)
 * - TransformControls attaches via ref após mount
 * - OrbitControls desabilitado automaticamente durante drag (makeDefault)
 */
export function CutPlaneMesh({
  plane,
  isSelected,
  transformMode,
  diskRadius,
  onSelect,
  onPlaneMoved,
  onDragEnd,
}: CutPlaneMeshProps) {
  const meshRef = useRef<THREE.Object3D>(null);
  const quaternion = new THREE.Quaternion(
    plane.qx,
    plane.qy,
    plane.qz,
    plane.qw,
  );
  const { fill, border } = getPlaneColors(plane.source, isSelected);

  const handleChange = useCallback(() => {
    if (!meshRef.current) return;
    const p = meshRef.current.position;
    const q = meshRef.current.quaternion;
    onPlaneMoved(plane.id, p.x, p.y, p.z, q.x, q.y, q.z, q.w);
  }, [plane.id, onPlaneMoved]);

  const handleMouseUp = useCallback(() => {
    handleChange();
    onDragEnd();
  }, [handleChange, onDragEnd]);

  return (
    <>
      {/* Disco preenchido semi-transparente */}
      <mesh
        ref={meshRef}
        position={[plane.px, plane.py, plane.pz]}
        quaternion={quaternion}
        onClick={(e) => {
          e.stopPropagation();
          onSelect(plane.id);
        }}
      >
        <circleGeometry args={[diskRadius, 64]} />
        <meshBasicMaterial
          color={fill}
          transparent
          opacity={0.3}
          side={THREE.DoubleSide}
          depthWrite={false}
        />
      </mesh>

      {/* Borda do disco para melhor visibilidade */}
      <mesh position={[plane.px, plane.py, plane.pz]} quaternion={quaternion}>
        <ringGeometry args={[diskRadius * 0.97, diskRadius, 64]} />
        <meshBasicMaterial
          color={border}
          side={THREE.DoubleSide}
          depthWrite={false}
        />
      </mesh>

      {/* TransformControls ativado apenas quando este plano está selecionado */}
      {isSelected && (
        <TransformControls
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          object={meshRef as any}
          mode={transformMode}
          onChange={handleChange}
          onMouseUp={handleMouseUp}
          size={0.75}
        />
      )}
    </>
  );
}

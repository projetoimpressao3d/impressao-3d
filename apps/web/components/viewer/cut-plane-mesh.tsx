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
 * Disco visual de um plano de corte + TransformControls quando selecionado.
 *
 * - PlaneGeometry com normal padrão [0,0,1] (plano XY)
 * - Quaternion aplicado via prop `quaternion` do mesh
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
  // useRef<THREE.Object3D> para compatibilidade com TransformControls
  const meshRef = useRef<THREE.Object3D>(null);
  const quaternion = new THREE.Quaternion(
    plane.qx,
    plane.qy,
    plane.qz,
    plane.qw,
  );

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
      {/* Disco visual do plano de corte */}
      <mesh
        ref={meshRef}
        position={[plane.px, plane.py, plane.pz]}
        quaternion={quaternion}
        onClick={(e) => {
          e.stopPropagation();
          onSelect(plane.id);
        }}
      >
        {/* Disco preenchido semi-transparente */}
        <circleGeometry args={[diskRadius, 64]} />
        <meshBasicMaterial
          color={isSelected ? "#f59e0b" : "#a78bfa"}
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
          color={isSelected ? "#f59e0b" : "#7c3aed"}
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

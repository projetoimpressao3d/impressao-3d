"use client";

import { useMemo } from "react";
import * as THREE from "three";
import type { BuildPlate } from "@/types/database";

interface BuildPlateBoxProps {
  plate: BuildPlate;
}

/**
 * Caixa wireframe representando a mesa de trabalho na cena 3D.
 * Posicionada centrada na origem (igual ao modelo).
 * Cor verde = modelo cabe | vermelha = não cabe (determinado pelo overlay, não aqui).
 * Aqui a cor é sempre neutra — o overlay cuida da comparação textual.
 */
export function BuildPlateBox({ plate }: BuildPlateBoxProps) {
  // Mapear dimensões da impressora para Three.js:
  // print X → three X (largura)
  // print Y → three Z (profundidade)
  // print Z → three Y (altura/cima)
  const {
    build_volume_x_mm: px,
    build_volume_y_mm: py,
    build_volume_z_mm: pz,
  } = plate;

  const edges = useMemo(() => {
    const geometry = new THREE.BoxGeometry(px, pz, py);
    return new THREE.EdgesGeometry(geometry);
  }, [px, py, pz]);

  return (
    <group>
      {/* Wireframe das arestas — azul/ciano para diferenciar do modelo */}
      <lineSegments geometry={edges}>
        <lineBasicMaterial color="#22d3ee" linewidth={1} />
      </lineSegments>

      {/* Face inferior (base) opaca semi-transparente como referência visual */}
      <mesh position={[0, -pz / 2, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[px, py]} />
        <meshBasicMaterial
          color="#22d3ee"
          transparent
          opacity={0.06}
          side={THREE.DoubleSide}
          depthWrite={false}
        />
      </mesh>

      {/* Faces laterais semi-transparentes */}
      <mesh>
        <boxGeometry args={[px, pz, py]} />
        <meshBasicMaterial
          color="#22d3ee"
          transparent
          opacity={0.04}
          side={THREE.BackSide}
          depthWrite={false}
        />
      </mesh>
    </group>
  );
}

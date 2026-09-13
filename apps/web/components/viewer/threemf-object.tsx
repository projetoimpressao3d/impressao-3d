"use client";

import { useLoader } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { ThreeMFLoader } from "three/examples/jsm/loaders/3MFLoader.js";

interface ThreeMFObjectProps {
  url: string;
  onBboxChange: (bbox: THREE.Box3) => void;
  /** Callback com posições de vértices (após centralização) para cálculo de bboxes por peça. */
  onGeometryReady?: (positions: Float32Array) => void;
  /** Opacidade do material (padrão: 1.0). */
  opacity?: number;
  /**
   * Se true (padrão), preserva as cores originais do arquivo 3MF (paint_color do Bambu Studio).
   * Se false, aplica a cor sólida `overrideColor` em todos os meshes.
   */
  showOriginalColors?: boolean;
  /** Cor de override quando showOriginalColors=false. */
  overrideColor?: string;
}

/**
 * Carrega um arquivo 3MF e o renderiza como cena Three.js.
 * O ThreeMFLoader retorna um Object3D (Group com múltiplos meshes).
 * Centra o grupo na origem e reporta a bounding box original.
 *
 * Por padrão, preserva as cores originais do 3MF (pintadas no Bambu Studio).
 * Isso garante que o usuário veja imediatamente as cores de cada filamento.
 */
export function ThreeMFObject({
  url,
  onBboxChange,
  onGeometryReady,
  opacity = 1,
  showOriginalColors = true,
  overrideColor = "#6366f1",
}: ThreeMFObjectProps) {
  // ThreeMFLoader retorna THREE.Group
  const group = useLoader(
    ThreeMFLoader as unknown as typeof THREE.ObjectLoader,
    url,
  ) as unknown as THREE.Group;
  const groupRef = useRef<THREE.Group>(null);

  // Processar o grupo: centrar na origem
  const { centeredGroup, originalBbox } = useMemo(() => {
    const g = group.clone(true);

    // Calcular bounding box antes de mover
    const bbox = new THREE.Box3().setFromObject(g);
    const center = new THREE.Vector3();
    bbox.getCenter(center);

    // Centralizar na origem
    g.position.sub(center);

    return { centeredGroup: g, originalBbox: bbox };
  }, [group]);

  useEffect(() => {
    onBboxChange(originalBbox);
  }, [originalBbox, onBboxChange]);

  // Aplicar material — preservar cores originais ou aplicar override
  useEffect(() => {
    centeredGroup.traverse((child) => {
      if (child instanceof THREE.Mesh) {
        if (showOriginalColors) {
          // Preservar a cor original do 3MF
          const existingMat = Array.isArray(child.material)
            ? child.material[0]
            : child.material;
          const existingColor =
            existingMat instanceof THREE.Material &&
            "color" in existingMat &&
            existingMat.color instanceof THREE.Color
              ? existingMat.color.clone()
              : new THREE.Color(overrideColor);

          child.material = new THREE.MeshStandardMaterial({
            color: existingColor,
            roughness: 0.45,
            metalness: 0.1,
            side: THREE.DoubleSide,
            transparent: opacity < 1,
            opacity,
          });
        } else {
          child.material = new THREE.MeshStandardMaterial({
            color: overrideColor,
            roughness: 0.45,
            metalness: 0.1,
            side: THREE.DoubleSide,
            transparent: opacity < 1,
            opacity,
          });
        }
        child.castShadow = true;
      }
    });
  }, [centeredGroup, opacity, showOriginalColors, overrideColor]);

  // Extrair e concatenar posições de vértices de todos os sub-meshes
  useEffect(() => {
    if (!onGeometryReady) return;

    const allPositions: number[] = [];
    centeredGroup.updateMatrixWorld(true);
    centeredGroup.traverse((child) => {
      if (child instanceof THREE.Mesh && child.geometry) {
        const geo = child.geometry as THREE.BufferGeometry;
        // Converter coordenadas locais para o espaço do grupo (já centrado)
        const posAttr = geo.attributes.position;
        if (posAttr) {
          const worldMatrix = child.matrixWorld;
          const tempVec = new THREE.Vector3();
          for (let i = 0; i < posAttr.count; i++) {
            tempVec.fromBufferAttribute(posAttr, i);
            tempVec.applyMatrix4(worldMatrix);
            allPositions.push(tempVec.x, tempVec.y, tempVec.z);
          }
        }
      }
    });

    if (allPositions.length > 0) {
      onGeometryReady(new Float32Array(allPositions));
    }
  }, [centeredGroup, onGeometryReady]);

  return <primitive ref={groupRef} object={centeredGroup} />;
}

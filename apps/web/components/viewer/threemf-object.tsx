"use client";

import { useLoader } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { ThreeMFLoader } from "three/examples/jsm/loaders/3MFLoader.js";

interface ThreeMFObjectProps {
  url: string;
  onBboxChange: (bbox: THREE.Box3) => void;
}

/**
 * Carrega um arquivo 3MF e o renderiza como cena Three.js.
 * O ThreeMFLoader retorna um Object3D (Group com múltiplos meshes).
 * Centra o grupo na origem e reporta a bounding box original.
 */
export function ThreeMFObject({ url, onBboxChange }: ThreeMFObjectProps) {
  // ThreeMFLoader retorna THREE.Group
  const group = useLoader(ThreeMFLoader as unknown as typeof THREE.ObjectLoader, url) as unknown as THREE.Group;
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

  // Aplicar material padrão a todos os meshes do grupo para iluminação consistente
  useEffect(() => {
    centeredGroup.traverse((child) => {
      if (child instanceof THREE.Mesh) {
        child.material = new THREE.MeshStandardMaterial({
          color: "#6366f1",
          roughness: 0.45,
          metalness: 0.1,
          side: THREE.DoubleSide,
        });
        child.castShadow = true;
      }
    });
  }, [centeredGroup]);

  return <primitive ref={groupRef} object={centeredGroup} />;
}
